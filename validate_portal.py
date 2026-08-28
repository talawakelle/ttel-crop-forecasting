from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
PORTAL = ROOT / "portal"
errors = []

db = sqlite3.connect(PORTAL / "data" / "portal.db")
manager_accounts = db.execute("SELECT COUNT(*) FROM users WHERE role='manager' AND active=1").fetchone()[0]
admin_accounts = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
active_links = db.execute("SELECT COUNT(*) FROM access_links WHERE active=1").fetchone()[0]
duplicate_links = db.execute("SELECT COUNT(*) FROM (SELECT user_id,COUNT(*) c FROM access_links WHERE active=1 GROUP BY user_id HAVING c<>1)").fetchone()[0]
invalid_hashes = db.execute("SELECT COUNT(*) FROM access_links WHERE active=1 AND length(token_hash)<>64").fetchone()[0]
user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
if manager_accounts != 33:
    errors.append(f"manager accounts: {manager_accounts}")
if admin_accounts != 1:
    errors.append(f"admin accounts: {admin_accounts}")
if active_links != 34 or duplicate_links or invalid_hashes:
    errors.append("active passwordless access links are invalid")
if {"password", "password_hash", "must_change_password"} & user_columns:
    errors.append("legacy password columns exist in the passwordless account database")

link_file = PORTAL / "private" / "estate_access_links.csv"
with link_file.open(newline="", encoding="utf-8") as handle:
    link_rows = list(csv.DictReader(handle))
if len(link_rows) != 34 or len({row["secure_access_link"] for row in link_rows}) != 34:
    errors.append("private access-link distribution file is invalid")
if any("password" in key.lower() and key != "password_required" for key in link_rows[0]):
    errors.append("password field exists in passwordless distribution file")
if any(row["password_required"] != "NO" for row in link_rows):
    errors.append("an access row requires a password")

actuals = pd.read_csv(ROOT / "outputs" / "prompt_daily_actuals.csv")
for forbidden in ["employee_id", "employee_name", "employee_epf_no", "super_name"]:
    if forbidden in actuals.columns:
        errors.append(f"personal column retained: {forbidden}")
if actuals["estate"].nunique() != 33 or len(actuals) != 365:
    errors.append("PROMPT daily actual coverage invalid")
audit = json.loads((ROOT / "outputs" / "prompt_actuals_import_audit.json").read_text())
if float(audit["max_daily_summary_difference_kg"]) != 0:
    errors.append("PROMPT reconciliation difference is not zero")

projection = pd.read_csv(ROOT / "outputs" / "five_year_daily_projection.csv")
counts = projection.groupby("estate").size()
if projection["estate"].nunique() != 33 or set(counts) != {1826}:
    errors.append("five-year daily projection coverage invalid")
if projection["best_practice_kg"].notna().any():
    errors.append("best-practice values were populated without GAP model data")

server_text = (PORTAL / "server.mjs").read_text(encoding="utf-8")
for required in ["Actual value", "Current-practice forecast", "Best-practice forecast", "Maximum five years"]:
    if required not in server_text:
        errors.append(f"graph control missing: {required}")
if "String(rawValue).trim() === ''" not in server_text:
    errors.append("blank forecast values are not explicitly excluded from graph aggregation")

result = {
    "status": "PASS" if not errors else "FAIL",
    "manager_accounts": manager_accounts,
    "administrator_accounts": admin_accounts,
    "passwordless_access_links": active_links,
    "automated_actual_estates": int(actuals["estate"].nunique()),
    "automated_actual_daily_rows": int(len(actuals)),
    "actual_reconciliation_max_difference_kg": float(audit["max_daily_summary_difference_kg"]),
    "five_year_projection_estates": int(projection["estate"].nunique()),
    "five_year_projection_rows": int(len(projection)),
    "best_practice_values_fabricated": bool(projection["best_practice_kg"].notna().any()),
    "errors": errors,
}
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
