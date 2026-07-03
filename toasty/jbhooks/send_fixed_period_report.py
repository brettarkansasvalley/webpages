#!/usr/bin/env python3
"""
This script generates a consolidated worker report for fixed, non-overlapping 
14-day periods based on a defined anchor date. It is designed for periodic 
execution via cron.
"""
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

# --- CONFIGURATION ---
# The anchor date when data entry began. All 14-day periods are calculated from here.
ANCHOR_DATE = date(2025, 7, 31)

# Email (password from environment / .env)
def _load_env(path):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_load_env(os.path.join(_BASE_DIR, ".env"))
_load_env(os.path.join(os.path.dirname(_BASE_DIR), ".env"))

SENDER_EMAIL = "mss@arkansasvalley.com"
SENDER_PASSWORD = os.environ["GMAIL_SENDER_PASSWORD"]
RECIPIENT_EMAIL = "margo@arkansasvalley.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_FILE = os.path.join(BASE_DIR, 'tip_distribution.db')
OUTPUT_DIR = os.path.join(BASE_DIR, 'generated_reports')

def get_consolidated_report_query():
    """Returns the SQL query for the consolidated report."""
    return """
        WITH DailyActivities AS (
            SELECT
                substr(s.date, 7, 4) || '-' || substr(s.date, 1, 2) || '-' || substr(s.date, 4, 2) AS "Date",
                s.server AS "Worker", 'Server' AS "Job Title", s.cash_tips AS "Cash Tips",
                s.non_cash_tips AS "Non-Cash Tips", s.gratuity AS "Gratuity",
                s.sum_tips_for_payout AS "Tips Paid Out", s.net_sales AS "Net Sales",
                0 AS "Tips Received"
            FROM servers s
            WHERE substr(s.date, 7, 4) || '-' || substr(s.date, 1, 2) || '-' || substr(s.date, 4, 2) BETWEEN :start_date AND :end_date
            UNION ALL
            SELECT
                substr(b.date, 7, 4) || '-' || substr(b.date, 1, 2) || '-' || substr(b.date, 4, 2) AS "Date",
                b.bartender AS "Worker", 'Bartender' AS "Job Title", b.cash_tips AS "Cash Tips",
                b.credit_tips AS "Non-Cash Tips", 0 AS "Gratuity",
                b.sum_tips_for_payout AS "Tips Paid Out", b.net_sales AS "Net Sales",
                0 AS "Tips Received"
            FROM bartenders b
            WHERE substr(b.date, 7, 4) || '-' || substr(b.date, 1, 2) || '-' || substr(b.date, 4, 2) BETWEEN :start_date AND :end_date
            UNION ALL
            SELECT
                date(c.timestamp) AS "Date", c.worker_name AS "Worker",
                REPLACE(c.reason, ' payout', '') AS "Job Title", 0, 0, 0, 0, 0, ABS(c.amount)
            FROM cashbox_ledger c
            WHERE c.reason LIKE '%payout' AND c.amount < 0 AND date(c.timestamp) BETWEEN :start_date AND :end_date
        )
        SELECT
            "Date", "Worker", GROUP_CONCAT(DISTINCT "Job Title") AS "Job Title",
            ROUND(SUM("Cash Tips"), 2) AS "Cash Tips", ROUND(SUM("Non-Cash Tips"), 2) AS "Non-Cash Tips",
            ROUND(SUM("Gratuity"), 2) AS "Gratuity", ROUND(SUM("Tips Paid Out"), 2) AS "Tips Paid Out",
            ROUND(SUM("Net Sales"), 2) AS "Net Sales", ROUND(SUM("Tips Received"), 2) AS "Tips Received",
            CASE WHEN SUM("Net Sales") > 0 THEN ROUND((SUM("Cash Tips") + SUM("Non-Cash Tips") + SUM("Gratuity")) * 100.0 / SUM("Net Sales"), 2) ELSE 0 END AS "Tip % of Sales"
        FROM DailyActivities
        GROUP BY "Date", "Worker"
        ORDER BY "Date" DESC, "Worker";
    """

def send_email_with_attachment(subject, body, recipient, filepath):
    """Composes and sends an email with an attachment."""
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with open(filepath, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(filepath)}")
        msg.attach(part)

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent successfully to {recipient}")
    except Exception as e:
        print(f"Error sending email: {e}")

def generate_and_send_report():
    """Generates a report for the most recently completed 14-day period and sends it."""
    today = date.today()
    
    # --- ROBUST DATE LOGIC: FIXED 14-DAY PERIODS ---
    days_since_anchor = (today - ANCHOR_DATE).days
    if days_since_anchor < 14:
        print(f"Not enough time has passed for the first report. Days passed: {days_since_anchor}.")
        return

    periods_passed = days_since_anchor // 14
    
    end_date = ANCHOR_DATE + timedelta(days=(periods_passed * 14) - 1)
    start_date = end_date - timedelta(days=13)
    
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    print(f"[{datetime.now()}] Generating report for fixed period: {start_date_str} to {end_date_str}")

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    try:
        conn = sqlite3.connect(DATABASE_FILE)
        query = get_consolidated_report_query()
        df = pd.read_sql_query(query, conn, params={'start_date': start_date_str, 'end_date': end_date_str})

        if df.empty:
            print("No data found for the period. Email will not be sent.")
            return

        filename = f"Fixed_Period_Report_{start_date_str}_to_{end_date_str}.csv"
        filepath = os.path.join(OUTPUT_DIR, filename)
        df.to_csv(filepath, index=False)
        print(f"Report saved to: {filepath}")

        subject = f"Bi-Weekly Consolidated Tip Report: {start_date_str} to {end_date_str}"
        body = f"Attached is the consolidated tip report for the period from {start_date_str} to {end_date_str}."
        send_email_with_attachment(subject, body, RECIPIENT_EMAIL, filepath)

    except Exception as e:
        print(f"An error occurred during report generation: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    generate_and_send_report()
