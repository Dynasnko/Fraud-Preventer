import sqlite3
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
db_path = os.path.join(_PROJECT_ROOT, "AllInOneProject", "chroma_dbs", "scam_records.sqlite3")

if not os.path.exists(db_path):
    print("Database not found:", db_path)
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get total count
cursor.execute("SELECT COUNT(*) FROM scam_cases")
print("Total records:", cursor.fetchone()[0])

# Get sum of loss
cursor.execute("SELECT SUM(loss_amount) FROM scam_cases")
print("Total loss:", cursor.fetchone()[0])

# Get sample records
cursor.execute("SELECT city, title, platforms, scam_accounts FROM scam_cases LIMIT 5")
print("Samples:", cursor.fetchall())

conn.close()
