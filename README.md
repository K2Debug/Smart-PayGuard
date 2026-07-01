# PayTrace

**Mobile Money Fraud Detector** — AI-powered anomaly detection for mobile money transaction datasets. Upload a file, run detection, and get risk-scored sender profiles, flagged transactions, charts, and CSV exports from a single web dashboard.

## Features

- **Isolation Forest** - unsupervised ML to catch multivariate outliers in transaction patterns
- **Z-Score analysis** - flags extreme amounts that deviate statistically from normal behaviour
- **Rule engine** - business rules for self-transfers, anonymous senders, odd-hour activity (00:00-04:59), and severely negative balances
- **Sender profiling** - composite risk score (0-100) with HIGH / MEDIUM / LOW / CLEAN labels
- **Interactive dashboard** - upload preview, results tables, Chart.js visualisations, alert logs, and CSV downloads

## Tech Stack

| Layer | Tools |
|-------|-------|
| Backend | Python, Flask |
| ML / stats | scikit-learn, scipy, pandas, numpy |
| Frontend | HTML, CSS, JavaScript, Chart.js |

## Dataset Format

Upload **CSV**, **Excel** (`.xlsx` / `.xls`), or **JSON**. The file must include these columns:

| Column | Description |
|--------|-------------|
| `Date` | Transaction date |
| `Time` | Transaction time |
| `Sender` | Sender identifier |
| `Receiver` | Receiver identifier |
| `Amount` | Transaction amount |
| `Balance` | Account balance after transaction |
| `provider` | Mobile money provider |
| `Region Sent` | Origin region |
| `Region Received` | Destination region |

A sample file with 100 synthetic records is included: `sample_transactions_100.csv`.

## Installation

```bash
git clone https://github.com/K2Debug/PayTrace-Mobile-Money-Fraud-Detector.git
cd PayTrace-Mobile-Money-Fraud-Detector
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Usage

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

1. Go to **Upload Dataset** and drag-and-drop or browse for your file.
2. Click **Run Detection** to process the dataset.
3. Review results on **Results**, **Visualizations**, **Reports**, and **Alert Logs**.

## How Detection Works

Each transaction is scored using three layers:

1. **Isolation Forest** (200 estimators, 5% contamination) on scaled features: log amount, hour, day of week, weekend flag, odd-hour flag, self-transfer, anonymous sender, same-region flag, negative balance, and provider dummies.
2. **Z-Score** on log-transformed amounts - flags values with |Z| > 3.
3. **Rules** - self-transfer, anonymous sender, odd-hour window, balance below -2,000,000.

A transaction is flagged if any ML flag or key rule fires. Senders with flagged transactions receive a composite risk score based on fraud rate, flagged count, self-transfers, odd-hour activity, and Isolation Forest scores.

## Project Structure

```
PayTrace-Mobile-Money-Fraud-Detector/
|-- app.py
|-- requirements.txt
|-- sample_transactions_100.csv
|-- README.md
`-- templates/
    `-- index.html
```

| Path | Purpose |
|------|---------|
| `app.py` | Flask app and detection pipeline |
| `requirements.txt` | Python dependencies |
| `sample_transactions_100.csv` | Sample test dataset (100 rows) |
| `templates/index.html` | Dashboard UI |
