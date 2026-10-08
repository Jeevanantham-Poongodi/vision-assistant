# backend/tools/check_supabase.py
"""Checks the Supabase setup from backend/.env (BE-09). Owner: Coder 3.

    python -m tools.check_supabase      (from backend/)

Prints whether the URL and key are set (never their values), whether each table from
db/migrations/001_init.sql exists, and the demo users. Exit code 0 = ready for FEATURE_ALERTS_DB=true."""
import sys

from config import settings

TABLES = {  # table -> a column every row has
    "app_users": "id",
    "guardian_links": "guardian_id",
    "sessions": "id",
    "alerts": "id",
    "location_pings": "id",
}


def main() -> int:
    print("SUPABASE_URL set:              ", bool(settings.supabase_url))
    print("SUPABASE_SERVICE_ROLE_KEY set: ", bool(settings.supabase_service_role_key))
    print("FEATURE_ALERTS_DB:             ", settings.feature_alerts_db)
    if not (settings.supabase_url and settings.supabase_service_role_key):
        print("FAIL: set both in backend/.env (Project Settings -> Data API / API Keys)")
        return 1
    from db.client import SupabaseClient

    try:
        client = SupabaseClient(settings.supabase_url, settings.supabase_service_role_key)
    except Exception as exc:
        print(f"FAIL: cannot create the client ({type(exc).__name__}). Is SUPABASE_URL https://<project>.supabase.co?")
        return 1
    ok = True
    for table, column in TABLES.items():
        try:
            rows = client.select(table, column)
            print(f"  table {table:<15} ok ({len(rows)} rows)")
        except Exception as exc:
            ok = False
            print(f"  table {table:<15} MISSING or unreadable: {client.safe_error(exc)}")
    if not ok:
        print("FAIL: run backend/db/migrations/001_init.sql in the Supabase SQL editor")
        return 1
    users = client.select("app_users", "name, role")
    print("Users:", ", ".join(f"{u['name']} ({u['role']})" for u in users) or "none - run the seed part of 001_init.sql")
    print("PASS" + ("" if settings.feature_alerts_db else "  (set FEATURE_ALERTS_DB=true to use it)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
