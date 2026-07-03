import smtplib
import sqlite3
import pandas as pd
import os
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# --- Email Configuration (password from environment / .env) ---
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

sender_email = "mss@arkansasvalley.com"
sender_password = os.environ["GMAIL_SENDER_PASSWORD"]  # Gmail App Password
recipient_email = "margo@arkansasvalley.com"
#recipient_email = "mss@arkansasvalley.com"
subject = "Daily Tip Report"

# --- Database Configuration ---
db_path = "/home/hooksadmin/jbhooks/tip_distribution.db"  # IMPORTANT! Use the absolute path
tables_to_export = ['bartenders', 'servers', 'payouts']
csv_attachments = []

# --- Connect to DB and Export Tables to CSV ---
try:
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    print("Successfully connected to the database.")

    # Export each table to a CSV file
    for table in tables_to_export:
        df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
        csv_filename = f"{table}_report.csv"
        df.to_csv(csv_filename, index=False)
        csv_attachments.append(csv_filename)
        print(f"Table '{table}' exported to '{csv_filename}'.")

    conn.close()

except Exception as e:
    print(f"Error reading the database or exporting tables: {e}")
    exit()

# --- Create and Send the Email ---
try:
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject

    # Attach each generated CSV file
    for file in csv_attachments:
        with open(file, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {os.path.basename(file)}")
        msg.attach(part)
        print(f"File '{file}' attached to the email.")

    # Send the email
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()
    server.login(sender_email, sender_password)
    server.send_message(msg)
    server.quit()
    print(f"Email sent successfully to {recipient_email}")

finally:
    # --- Cleanup: Delete the temporary CSV files ---
    print("Cleaning up temporary files...")
    for file in csv_attachments:
        if os.path.exists(file):
            os.remove(file)
            print(f"File '{file}' deleted.")
