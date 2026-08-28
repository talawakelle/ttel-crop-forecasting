from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent
errors: list[str] = []


def rows(name: str) -> list[dict[str, str]]:
    with (ROOT / "outputs" / name).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


summary = rows("portfolio_summary.csv")
forecasts = rows("portfolio_forecasts.csv")
workforce = rows("workforce_estate_data_audit.csv")
actuals = rows("prompt_daily_actuals.csv")
canonical = {row["estate"] for row in summary}

if len(summary) != 33 or len(canonical) != 33:
    errors.append("crop portfolio does not contain 33 unique estates")
if len(workforce) != 33 or {row["estate"] for row in workforce} != canonical:
    errors.append("workforce audit does not match the 33-estate crop portfolio")
if len({(row["plantation_id"], row["estate_id"]) for row in workforce}) != 33:
    errors.append("plantation/estate identities are not unique")
if any(str(row["identity_mismatch"]).lower() == "true" for row in workforce):
    errors.append("at least one workforce source has an estate identity mismatch")
if any(key in workforce[0] for key in ["employee_id", "employee_name", "employee_internal_no"]):
    errors.append("raw employee identifiers leaked into the workforce audit")

by_estate: dict[str, list[dict[str, str]]] = {}
for row in forecasts:
    by_estate.setdefault(row["estate"], []).append(row)
for estate in canonical:
    horizons = sorted(int(row["horizon_weeks"]) for row in by_estate.get(estate, []))
    if horizons != [1, 2, 3, 4]:
        errors.append(f"{estate}: crop horizons are {horizons}")

portal_source = (ROOT / "portal" / "server.mjs").read_text(encoding="utf-8")
for required in [
    "Workforce Planning", "RL DISABLED", "NO AUTOMATIC MOVES",
    "allowedEstate(session", "Current-practice forecast", "Best-practice forecast",
]:
    if required not in portal_source:
        errors.append(f"portal control missing: {required}")

db = sqlite3.connect(ROOT / "portal" / "data" / "portal.db")
managers = db.execute("SELECT COUNT(*) FROM users WHERE role='manager' AND active=1").fetchone()[0]
admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
if managers != 33 or admins != 1:
    errors.append(f"account coverage is managers={managers}, admins={admins}")

access_path = ROOT / "portal" / "private" / "estate_access_links.csv"
with access_path.open(newline="", encoding="utf-8-sig") as handle:
    access_rows = list(csv.DictReader(handle))
if len(access_rows) != 34 or len({row["secure_access_link"] for row in access_rows}) != 34:
    errors.append("passwordless access-link distribution does not contain 34 unique links")
for row in access_rows:
    token = row["secure_access_link"].rsplit("/", 1)[-1]
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    match = db.execute(
        """SELECT u.role,COALESCE(u.estate,'ALL ESTATES')
           FROM access_links a JOIN users u ON u.id=a.user_id
           WHERE a.token_hash=? AND a.active=1 AND u.active=1""",
        (token_hash,),
    ).fetchone()
    if not match or match != (row["role"], row["estate"]):
        errors.append(f"access link does not match its account: {row['estate']}")

readiness = {row["readiness"] for row in workforce}
result = {
    "status": "PASS" if not errors else "FAIL",
    "crop_estates": len(canonical),
    "workforce_estates": len(workforce),
    "actual_estates": len({row["estate"] for row in actuals}),
    "manager_accounts": managers,
    "administrator_accounts": admins,
    "workforce_readiness_states": sorted(readiness),
    "rl_training_authorized": False,
    "automatic_employee_moves_authorized": False,
    "errors": errors,
}
(ROOT / "outputs" / "integrated_platform_validation.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(json.dumps(result, indent=2))
raise SystemExit(1 if errors else 0)
