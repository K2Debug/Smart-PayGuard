// ── State ──
let uploadedFile  = null;
let detectionData = null;
let charts        = {};

// ── Icons ──
function refreshIcons() {
  if (window.lucide) lucide.createIcons();
}

// ── Theme ──
function initTheme() {
  const saved = localStorage.getItem('paytrace-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  updateThemeToggleIcon();
}

function toggleTheme() {
  const root = document.documentElement;
  const current = root.getAttribute('data-theme');
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  let next;
  if (current === 'dark') next = 'light';
  else if (current === 'light') next = 'dark';
  else next = prefersDark ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  localStorage.setItem('paytrace-theme', next);
  updateThemeToggleIcon();
  if (detectionData) renderCharts(detectionData);
}

function updateThemeToggleIcon() {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;
  const theme = document.documentElement.getAttribute('data-theme');
  const isDark = theme === 'dark' ||
    (!theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
  btn.innerHTML = isDark
    ? '<i data-lucide="sun"></i>'
    : '<i data-lucide="moon"></i>';
  btn.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
  refreshIcons();
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ── Navigation ──
document.querySelectorAll('.nav li').forEach(li => {
  li.addEventListener('click', e => {
    e.preventDefault();
    if (li.classList.contains('nav-locked')) return;
    showPage(li.dataset.page);
  });
});

function showPage(name) {
  document.querySelectorAll('.nav li').forEach(l => l.classList.remove('active'));
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const li = document.querySelector(`.nav li[data-page="${name}"]`);
  if (li && !li.classList.contains('nav-locked')) li.classList.add('active');
  const page = document.getElementById('page-' + name);
  if (page) page.classList.add('active');
}

function unlockAnalysis() {
  const nav = document.getElementById('navAnalysis');
  if (nav) nav.classList.remove('nav-locked');
}

function showAnalysisTab(tab) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  const btn = document.querySelector(`.tab-btn[data-tab="${tab}"]`);
  const panel = document.getElementById('tab-' + tab);
  if (btn) btn.classList.add('active');
  if (panel) panel.classList.add('active');
}

// ── File Upload ──
const dropZone  = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');

dropZone.addEventListener('click', e => {
  if (e.target.closest('.browse-btn')) return;
  fileInput.click();
});

dropZone.addEventListener('dragover', e => {
  e.preventDefault();
  dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));

dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});

fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

function handleFile(file) {
  uploadedFile = file;
  const kb = (file.size / 1024).toFixed(1);
  document.getElementById('fileName').innerHTML =
    `<i data-lucide="file-text"></i><span>${file.name}</span>`;
  document.getElementById('fileSize').innerHTML =
    `${kb} KB <i data-lucide="check-circle"></i>`;
  document.getElementById('fileBadge').style.display = 'flex';
  document.getElementById('runBtn').disabled = false;
  document.querySelector('.run-hint').textContent =
    'Click to run anomaly detection on your dataset';
  showError('');

  const reader = new FileReader();
  reader.onload = e => {
    const text = e.target.result;
    const lines = text.split('\n').filter(l => l.trim());
    const headers = lines[0].split(',');
    const rows = lines.slice(1, 6);
    let html = `<table class="data-table"><thead><tr>${headers.slice(0, 6).map(h => `<th>${h.trim()}</th>`).join('')}</tr></thead><tbody>`;
    rows.forEach(r => {
      const cells = r.split(',');
      html += `<tr>${cells.slice(0, 6).map(c => `<td>${c.trim()}</td>`).join('')}</tr>`;
    });
    html += `</tbody></table><div class="table-note">Showing 5 of ${lines.length - 1} rows</div>`;
    document.getElementById('previewWrap').innerHTML = html;
    refreshIcons();
  };

  if (file.name.endsWith('.csv')) {
    reader.readAsText(file);
  } else {
    document.getElementById('previewWrap').innerHTML =
      `<div class="empty-state"><div class="e-icon"><i data-lucide="file-spreadsheet"></i></div>Preview not available for this format. File ready to upload.</div>`;
    refreshIcons();
  }
}

function showError(msg) {
  const b = document.getElementById('errorBanner');
  if (msg) {
    b.innerHTML = `<i data-lucide="alert-triangle"></i><span>${msg}</span>`;
    b.classList.add('show');
    refreshIcons();
  } else {
    b.classList.remove('show');
    b.innerHTML = '';
  }
}

// ── Run Detection ──
async function runDetection() {
  if (!uploadedFile) return;
  showError('');
  document.getElementById('spinner').classList.add('show');
  document.getElementById('runBtn').disabled = true;

  const form = new FormData();
  form.append('file', uploadedFile);

  try {
    const res  = await fetch('/predict', { method: 'POST', body: form });
    const data = await res.json();

    if (data.error) {
      showError(data.error);
    } else {
      detectionData = data;
      unlockAnalysis();
      renderResults(data);
      renderCharts(data);
      renderAlerts(data);
      renderReports();
      showPage('analysis');
      showAnalysisTab('overview');
    }
  } catch (err) {
    showError('Network error, is the server running? ' + err.message);
  } finally {
    document.getElementById('spinner').classList.remove('show');
    document.getElementById('runBtn').disabled = false;
  }
}

// ── Render Results ──
function renderResults(d) {
  document.getElementById('analysisEmpty').style.display = 'none';
  document.getElementById('analysisContent').style.display = 'block';

  document.getElementById('rTotal').textContent    = d.total_transactions.toLocaleString();
  document.getElementById('rFlagged').textContent  = d.flagged_transactions.toLocaleString();
  document.getElementById('rPct').textContent      = d.fraud_percentage + '% of total';
  document.getElementById('rSuspects').textContent = d.total_suspects.toLocaleString();
  document.getElementById('rHigh').textContent     = d.high_risk_count.toLocaleString();

  const sb = document.getElementById('suspectsBody');
  sb.innerHTML = '';
  d.top_suspects.forEach((s, i) => {
    const lvl = s.Risk_Level.split(' ')[0];
    sb.innerHTML += `<tr>
      <td>${i + 1}</td>
      <td>${s.Sender}</td>
      <td><strong>${s.Risk_Score}</strong>/100</td>
      <td><span class="badge ${lvl}">${s.Risk_Level}</span></td>
      <td>${s.Flagged_Txns}</td>
      <td>TZS ${Number(s.Suspicious_Amount).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
      <td>${s['Fraud_Rate_%']}%</td>
    </tr>`;
  });

  const maxSusp = Math.max(d.high_risk_count, d.medium_risk_count, d.low_risk_count, 1);
  document.getElementById('riskBreakdown').innerHTML = `
    ${bar('HIGH RISK',   d.high_risk_count,   maxSusp, 'red')}
    ${bar('MEDIUM RISK', d.medium_risk_count, maxSusp, 'amber')}
    ${bar('LOW RISK',    d.low_risk_count,    maxSusp, 'green')}
  `;

  const fb = document.getElementById('flaggedBody');
  fb.innerHTML = '';
  (d.flagged_sample || []).forEach(t => {
    fb.innerHTML += `<tr>
      <td>${t.Sender}</td><td>${t.Receiver}</td>
      <td>TZS ${Number(t.Amount).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
      <td>${t.Date}</td><td>${t.Fraud_Reason}</td>
    </tr>`;
  });
}

function bar(label, count, max, cls) {
  const pct = Math.round((count / max) * 100);
  return `<div class="bar-row">
    <span class="bar-label">${label}</span>
    <div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
    <span class="bar-count">${count}</span>
  </div>`;
}

// ── Chart.js theme (matches CSS tokens) ──
function chartTheme() {
  const tick = cssVar('--text-muted') || '#8B949E';
  const grid = cssVar('--chart-grid') || 'rgba(255, 255, 255, 0.08)';
  const axis = { ticks: { color: tick }, grid: { color: grid }, border: { color: grid } };
  return {
    legend: { labels: { color: tick, boxWidth: 12, padding: 14 } },
    scales: { x: axis, y: axis }
  };
}

function pieOptions() {
  const theme = chartTheme();
  return {
    plugins: { legend: { position: 'bottom', labels: theme.legend.labels } },
    cutout: '60%'
  };
}

function barScaleOptions(extra = {}) {
  const theme = chartTheme();
  return {
    indexAxis: 'y',
    plugins: { legend: { display: false } },
    scales: {
      x: { beginAtZero: true, ...theme.scales.x, ...extra.x },
      y: { ...theme.scales.y, ...extra.y }
    }
  };
}

// ── Render Charts ──
function renderCharts(d) {
  document.getElementById('chartsEmpty').style.display = 'none';
  document.getElementById('chartsContent').style.display = 'grid';

  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  const ACCENT  = cssVar('--accent')  || '#C41E3A';
  const RED     = cssVar('--danger')  || '#CF222E';
  const AMBER   = cssVar('--warning') || '#D4A017';
  const SUCCESS = cssVar('--success') || '#2EA44F';
  const GREY    = cssVar('--text-muted') || '#8B949E';

  Chart.defaults.color = cssVar('--text-muted') || '#8B949E';
  Chart.defaults.borderColor = cssVar('--chart-grid') || 'rgba(255, 255, 255, 0.08)';

  charts.risk = new Chart(document.getElementById('chartRisk'), {
    type: 'doughnut',
    data: {
      labels: ['High Risk', 'Medium Risk', 'Low Risk'],
      datasets: [{
        data: [d.high_risk_count, d.medium_risk_count, d.low_risk_count],
        backgroundColor: [RED, AMBER, SUCCESS],
        borderWidth: 0
      }]
    },
    options: pieOptions()
  });

  const reasons = d.reason_breakdown || {};
  charts.reasons = new Chart(document.getElementById('chartReasons'), {
    type: 'bar',
    data: {
      labels: Object.keys(reasons),
      datasets: [{
        label: 'Count',
        data: Object.values(reasons),
        backgroundColor: ACCENT,
        borderRadius: 4
      }]
    },
    options: barScaleOptions()
  });

  const clean = d.total_transactions - d.flagged_transactions;
  charts.split = new Chart(document.getElementById('chartSplit'), {
    type: 'pie',
    data: {
      labels: ['Flagged', 'Clean'],
      datasets: [{
        data: [d.flagged_transactions, clean],
        backgroundColor: [RED, GREY],
        borderWidth: 0
      }]
    },
    options: {
      plugins: { legend: { position: 'bottom', labels: chartTheme().legend.labels } }
    }
  });

  const top5 = (d.top_suspects || []).slice(0, 5);
  charts.top5 = new Chart(document.getElementById('chartTop5'), {
    type: 'bar',
    data: {
      labels: top5.map(s => s.Sender),
      datasets: [{
        label: 'Risk Score',
        data: top5.map(s => s.Risk_Score),
        backgroundColor: top5.map(s =>
          s.Risk_Level.startsWith('HIGH') ? RED :
          s.Risk_Level.startsWith('MEDIUM') ? AMBER : SUCCESS
        ),
        borderRadius: 4
      }]
    },
    options: barScaleOptions({ x: { max: 100 } })
  });
}

// ── Render Alerts ──
function renderAlerts(d) {
  const list = document.getElementById('alertsList');
  const suspects = d.top_suspects || [];
  if (!suspects.length) return;
  document.getElementById('alertsEmpty').style.display = 'none';
  list.innerHTML = suspects.slice(0, 15).map(s => {
    const lvl = s.Risk_Level.startsWith('HIGH') ? 'red' :
                s.Risk_Level.startsWith('MEDIUM') ? 'amber' : 'green';
    return `<div class="alert-item">
      <div class="alert-dot ${lvl}"></div>
      <div>
        <span class="alert-sender">${s.Sender}</span>
        <span class="badge ${s.Risk_Level.split(' ')[0]}" style="margin-left:8px">${s.Risk_Level}</span>
        <div class="alert-reason">Risk Score: ${s.Risk_Score}/100, ${s.Flagged_Txns} flagged transactions, TZS ${Number(s.Suspicious_Amount).toLocaleString(undefined, { maximumFractionDigits: 0 })} suspicious</div>
      </div>
    </div>`;
  }).join('');
}

// ── Reports ──
function renderReports() {
  document.getElementById('exportEmpty').style.display = 'none';
  document.getElementById('exportContent').style.display = 'block';
}

function downloadCSV(type) {
  if (!detectionData) return;
  let csv = '', filename = '';
  if (type === 'suspects') {
    const rows = detectionData.top_suspects;
    csv = 'Sender,Risk_Score,Risk_Level,Flagged_Txns,Suspicious_Amount,Fraud_Rate_%\n'
        + rows.map(r =>
          `${r.Sender},${r.Risk_Score},${r.Risk_Level},${r.Flagged_Txns},${r.Suspicious_Amount},${r['Fraud_Rate_%']}`
        ).join('\n');
    filename = 'paytrace_suspects.csv';
  } else {
    const rows = detectionData.flagged_sample || [];
    csv = 'Sender,Receiver,Amount,Date,Fraud_Reason\n'
        + rows.map(r =>
          `"${r.Sender}","${r.Receiver}",${r.Amount},"${r.Date}","${r.Fraud_Reason}"`
        ).join('\n');
    filename = 'paytrace_flagged_transactions.csv';
  }
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

// ── Tab bar clicks ──
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => showAnalysisTab(btn.dataset.tab));
});

// ── Init ──
initTheme();
refreshIcons();
