import os
import io
import sqlite3
import warnings
from datetime import datetime
from functools import wraps
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "change-this-to-a-random-secret-key-before-deploying"  # IMPORTANT: change this!

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


# ───────────────────────── DATABASE SETUP ─────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'analyst',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP,
            total_logins INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Every login attempt (success or failure) gets logged here
    c.execute("""
        CREATE TABLE IF NOT EXISTS login_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            email_attempted TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            success INTEGER NOT NULL,
            failure_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # Optional: track what each logged-in user does (e.g. ran detection)
    c.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

init_db()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def log_activity(user_id, action, details=""):
    conn = get_db()
    conn.execute(
        "INSERT INTO activity_log (user_id, action, details) VALUES (?, ?, ?)",
        (user_id, action, details)
    )
    conn.commit()
    conn.close()


def get_client_ip():
    # Works behind most proxies/hosts (Render, PythonAnywhere) and locally
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr


# ───────────────────────── LOGIN PROTECTION ─────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        if session.get("role") != "admin":
            return jsonify({'error': 'Admin access required.'}), 403
        return f(*args, **kwargs)
    return decorated


# ───────────────────────── AUTH ROUTES ─────────────────────────
@app.route('/register-page')
def register_page():
    return render_template('register.html')

@app.route('/login-page')
def login_page():
    return render_template('login.html')


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    full_name = (data.get('full_name') or '').strip()
    email     = (data.get('email') or '').strip().lower()
    password  = data.get('password') or ''

    if not full_name or not email or not password:
        return jsonify({'error': 'All fields are required.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'error': 'An account with this email already exists.'}), 400

    # First-ever registered user becomes admin automatically
    user_count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
    role = 'admin' if user_count == 0 else 'analyst'

    password_hash = generate_password_hash(password)
    conn.execute(
        "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (full_name, email, password_hash, role)
    )
    conn.commit()
    conn.close()

    return jsonify({'status': 'success', 'message': 'Account created! Please log in.'})


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email    = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    ip_addr    = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')[:255]

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    # ── Case: no such user ──
    if not user:
        conn.execute(
            "INSERT INTO login_activity (user_id, email_attempted, ip_address, user_agent, success, failure_reason) VALUES (?,?,?,?,?,?)",
            (None, email, ip_addr, user_agent, 0, "No account with this email")
        )
        conn.commit()
        conn.close()
        return jsonify({'error': 'Invalid email or password.'}), 401

    # ── Case: account disabled ──
    if not user['is_active']:
        conn.execute(
            "INSERT INTO login_activity (user_id, email_attempted, ip_address, user_agent, success, failure_reason) VALUES (?,?,?,?,?,?)",
            (user['id'], email, ip_addr, user_agent, 0, "Account disabled")
        )
        conn.commit()
        conn.close()
        return jsonify({'error': 'This account has been disabled. Contact an administrator.'}), 403

    # ── Case: wrong password ──
    if not check_password_hash(user['password_hash'], password):
        conn.execute(
            "INSERT INTO login_activity (user_id, email_attempted, ip_address, user_agent, success, failure_reason) VALUES (?,?,?,?,?,?)",
            (user['id'], email, ip_addr, user_agent, 0, "Incorrect password")
        )
        conn.commit()
        conn.close()
        return jsonify({'error': 'Invalid email or password.'}), 401

    # ── Success ──
    conn.execute(
        "INSERT INTO login_activity (user_id, email_attempted, ip_address, user_agent, success, failure_reason) VALUES (?,?,?,?,?,?)",
        (user['id'], email, ip_addr, user_agent, 1, None)
    )
    conn.execute(
        "UPDATE users SET last_login = CURRENT_TIMESTAMP, total_logins = total_logins + 1 WHERE id = ?",
        (user['id'],)
    )
    conn.commit()
    conn.close()

    session['user_id']   = user['id']
    session['full_name'] = user['full_name']
    session['email']     = user['email']
    session['role']      = user['role']
    session['login_time'] = datetime.utcnow().isoformat()

    return jsonify({'status': 'success', 'full_name': user['full_name'], 'role': user['role']})


@app.route('/logout')
def logout():
    if 'user_id' in session:
        log_activity(session['user_id'], 'logout')
    session.clear()
    return redirect(url_for('login_page'))


@app.route('/api/session')
def api_session():
    if "user_id" in session:
        return jsonify({
            'logged_in': True,
            'full_name': session['full_name'],
            'email': session['email'],
            'role': session.get('role', 'analyst')
        })
    return jsonify({'logged_in': False})


# ───────────────────────── MAIN APP (PROTECTED) ─────────────────────────
@app.route('/')
@login_required
def home():
    return render_template('index.html', full_name=session.get('full_name'), role=session.get('role'))


# ───────────────────────── ADMIN: ACTIVITY DASHBOARD ─────────────────────────
@app.route('/admin/activity')
@admin_required
def admin_activity_page():
    return render_template('activity.html', full_name=session.get('full_name'))


@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    conn = get_db()
    users = conn.execute("""
        SELECT id, full_name, email, role, is_active, created_at, last_login, total_logins
        FROM users ORDER BY created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route('/api/admin/login-activity')
@admin_required
def api_admin_login_activity():
    conn = get_db()
    rows = conn.execute("""
        SELECT la.id, la.email_attempted, la.ip_address, la.success, la.failure_reason, la.timestamp,
               u.full_name
        FROM login_activity la
        LEFT JOIN users u ON la.user_id = u.id
        ORDER BY la.timestamp DESC
        LIMIT 100
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/admin/toggle-user/<int:uid>', methods=['POST'])
@admin_required
def api_admin_toggle_user(uid):
    if uid == session['user_id']:
        return jsonify({'error': "You can't disable your own account."}), 400
    conn = get_db()
    user = conn.execute("SELECT is_active FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        conn.close()
        return jsonify({'error': 'User not found.'}), 404
    new_status = 0 if user['is_active'] else 1
    conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (new_status, uid))
    conn.commit()
    conn.close()
    return jsonify({'status': 'success', 'is_active': new_status})


# ───────────────────────── ML DETECTION LOGIC ─────────────────────────
def build_reason(row):
    r = []
    if row["Rule_Anonymous"]:    r.append("Anonymous sender")
    if row["Rule_SelfTransfer"]: r.append("Self-transfer")
    if row["Z_Flag"]:            r.append(f"Extreme amount (Z={row['ZScore']:.1f})")
    if row["Rule_OddHour"]:      r.append(f"Odd hour ({int(row['Hour']):02d}:xx)")
    if row["Rule_NegBalance"]:   r.append("Severely negative balance")
    if row["IF_Flag"] and not r: r.append("Multivariate outlier (Isolation Forest)")
    elif row["IF_Flag"] and r:   r.append("+ IF outlier")
    return "; ".join(r) if r else "—"

def risk_score(row, max_flagged):
    score  = (row["Fraud_Rate_%"] / 100) * 40
    score += (row["Flagged_Txns"] / max(max_flagged, 1)) * 25
    score += min(row["Self_Transfers"] * 5, 15)
    score += min(row["Odd_Hour_Txns"]  * 2, 10)
    score += min(row["Times_Received_Fraud"] * 2, 5)
    if row["Avg_IF_Score"] < -0.10:
        score += 5
    return round(min(score, 100), 1)

def risk_label(score):
    if score >= 60: return "HIGH RISK"
    if score >= 30: return "MEDIUM RISK"
    if score >= 10: return "LOW RISK"
    return "CLEAN"


@app.route('/predict', methods=['POST'])
@login_required
def predict():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    uploaded_file = request.files['file']
    if uploaded_file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    try:
        file_bytes = uploaded_file.read()
        filename = uploaded_file.filename.lower()

        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_bytes))
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(io.BytesIO(file_bytes))
        elif filename.endswith('.json'):
            df = pd.read_json(io.BytesIO(file_bytes))
        else:
            return jsonify({'error': 'Unsupported file format. Please upload CSV, Excel, or JSON.'}), 400

        total_transactions = len(df)
        if total_transactions == 0:
            return jsonify({'error': 'The uploaded dataset is empty.'}), 400

        df["DateTime"]       = pd.to_datetime(df["Date"].astype(str) + " " + df["Time"].astype(str), errors="coerce")
        df["Hour"]           = df["DateTime"].dt.hour.fillna(0)
        df["DayOfWeek"]      = df["DateTime"].dt.dayofweek.fillna(0)
        df["IsWeekend"]      = (df["DayOfWeek"] >= 5).astype(int)
        df["IsOddHour"]      = ((df["Hour"] >= 0) & (df["Hour"] < 5)).astype(int)
        df["IsSelfTransfer"] = (df["Sender"].str.strip() == df["Receiver"].str.strip()).astype(int)
        df["IsAnonymous"]    = (df["Sender"].str.strip().str.lower() == "anonymous").astype(int)
        df["IsSameRegion"]   = (df["Region Sent"].str.strip() == df["Region Received"].str.strip()).astype(int)
        df["LogAmount"]      = np.log1p(df["Amount"].clip(lower=0))
        df["NegBalance"]     = (df["Balance"] < -2_000_000).astype(int)

        provider_dummies = pd.get_dummies(df["provider"], prefix="prov")
        df = pd.concat([df, provider_dummies], axis=1)

        FEATURE_COLS = (["LogAmount", "Hour", "DayOfWeek", "IsWeekend",
                         "IsOddHour", "IsSelfTransfer", "IsAnonymous",
                         "IsSameRegion", "NegBalance"]
                        + [c for c in df.columns if c.startswith("prov_")])

        X    = df[FEATURE_COLS].fillna(0)
        X_sc = StandardScaler().fit_transform(X)

        iso = IsolationForest(n_estimators=200, contamination=0.05, random_state=42)
        df["IF_Score"] = iso.fit(X_sc).decision_function(X_sc)
        df["IF_Flag"]  = (iso.predict(X_sc) == -1).astype(int)

        df["ZScore"] = np.abs(stats.zscore(df["LogAmount"]))
        df["Z_Flag"] = (df["ZScore"] > 3.0).astype(int)

        df["Rule_SelfTransfer"] = df["IsSelfTransfer"]
        df["Rule_Anonymous"]    = df["IsAnonymous"]
        df["Rule_OddHour"]      = df["IsOddHour"]
        df["Rule_NegBalance"]   = df["NegBalance"]

        df["Fraud_Flag"] = ((df["IF_Flag"] == 1) | (df["Z_Flag"] == 1) |
                            (df["Rule_SelfTransfer"] == 1) | (df["Rule_Anonymous"] == 1)).astype(int)
        df["Fraud_Reason"] = df.apply(build_reason, axis=1)

        flagged_df = df[df["Fraud_Flag"] == 1].copy()
        n_fraud = int(df["Fraud_Flag"].sum())

        sender_profile = (
            df.groupby("Sender")
            .agg(
                Total_Txns        = ("Fraud_Flag", "count"),
                Flagged_Txns      = ("Fraud_Flag", "sum"),
                Total_Amount_Sent = ("Amount",     "sum"),
                Avg_IF_Score      = ("IF_Score",   "mean"),
                Self_Transfers    = ("IsSelfTransfer", "sum"),
                Odd_Hour_Txns     = ("IsOddHour",  "sum"),
                Neg_Balance_Txns  = ("NegBalance", "sum"),
            )
            .reset_index()
        )

        susp_amt = flagged_df.groupby("Sender")["Amount"].sum().reset_index(name="Suspicious_Amount")
        sender_profile = sender_profile.merge(susp_amt, on="Sender", how="left").fillna(0)

        recv_counts = flagged_df.groupby("Receiver").size().reset_index(name="Times_Received_Fraud")
        sender_profile = sender_profile.merge(recv_counts, left_on="Sender", right_on="Receiver", how="left").fillna(0)
        sender_profile["Times_Received_Fraud"] = sender_profile["Times_Received_Fraud"].astype(int)

        sender_profile["Fraud_Rate_%"] = (sender_profile["Flagged_Txns"] / sender_profile["Total_Txns"] * 100).round(1)

        max_f = sender_profile["Flagged_Txns"].max()
        sender_profile["Risk_Score"] = sender_profile.apply(lambda r: risk_score(r, max_f), axis=1)
        sender_profile["Risk_Level"] = sender_profile["Risk_Score"].apply(risk_label)

        suspects = sender_profile[sender_profile["Flagged_Txns"] > 0].sort_values("Risk_Score", ascending=False).reset_index(drop=True)

        n_high   = int((suspects["Risk_Level"] == "HIGH RISK").sum())
        n_medium = int((suspects["Risk_Level"] == "MEDIUM RISK").sum())
        n_low    = int((suspects["Risk_Level"] == "LOW RISK").sum())

        top_suspects_list = suspects.head(10)[["Sender", "Risk_Score", "Risk_Level", "Flagged_Txns", "Suspicious_Amount", "Fraud_Rate_%"]].to_dict(orient="records")
        flagged_sample = flagged_df[["Sender", "Receiver", "Amount", "Date", "Fraud_Reason"]].head(20).fillna("—").to_dict(orient="records")

        all_reasons = []
        for reason_str in df["Fraud_Reason"]:
            if reason_str != "—":
                for part in reason_str.split(";"):
                    p = part.strip()
                    if p and p != "+ IF outlier":
                        all_reasons.append(p)
        from collections import Counter
        reason_counts = dict(Counter(all_reasons).most_common(6))

        # Track that this user ran a detection
        log_activity(session['user_id'], 'ran_detection',
                     f"file={uploaded_file.filename}, total={total_transactions}, flagged={n_fraud}")

        return jsonify({
            'status': 'success',
            'total_transactions': total_transactions,
            'flagged_transactions': n_fraud,
            'fraud_percentage': round((n_fraud / total_transactions) * 100, 1),
            'total_suspects': len(suspects),
            'high_risk_count': n_high,
            'medium_risk_count': n_medium,
            'low_risk_count': n_low,
            'top_suspects': top_suspects_list,
            'flagged_sample': flagged_sample,
            'reason_breakdown': reason_counts
        })

    except Exception as e:
        import traceback
        return jsonify({'error': f"Processing Error: {str(e)}", 'trace': traceback.format_exc()}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
