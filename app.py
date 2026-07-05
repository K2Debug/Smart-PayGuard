import io
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
from scipy import stats
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)


# ───────────────────────── ML DETECTION LOGIC ─────────────────────────
def build_reason(row):
    r = []
    if row["Rule_Anonymous"]:    r.append("Sender is anonymous")
    if row["Rule_SelfTransfer"]: r.append("Sent money to themselves")
    if row["Z_Flag"]:            r.append(f"Amount much higher than usual ({row['ZScore']:.1f}x spread)")
    if row["Rule_OddHour"]:      r.append(f"Sent between midnight and 5 AM ({int(row['Hour']):02d}:xx)")
    if row["Rule_NegBalance"]:   r.append("Account balance very negative after payment")
    if row["IF_Flag"] and not r: r.append("Unusual pattern detected by AI model")
    elif row["IF_Flag"] and r:   r.append("Also flagged by AI model")
    return ", ".join(r) if r else "No specific reason"

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


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/predict', methods=['POST'])
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
            if reason_str != "No specific reason":
                for part in reason_str.split(","):
                    p = part.strip()
                    if p and p != "Also flagged by AI model":
                        all_reasons.append(p)
        from collections import Counter
        reason_counts = dict(Counter(all_reasons).most_common(6))

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
