"""Set the dashboard login password for an existing Supabase Auth user.

Run in your own terminal (input is hidden and never printed or logged):
    cd ~/Projects/FindingAHouse/backend
    poetry run python scripts/set_dashboard_password.py bsantiagopv@gmail.com

Uses the service-role key from .env, so it only works on this machine.
"""

import getpass
import sys

import httpx

from app.core.config import Settings

MIN_LENGTH = 12


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    email = sys.argv[1].strip().lower()
    s = Settings()
    base = s.supabase_url.strip().rstrip("/").removesuffix("/rest/v1")
    key = s.supabase_service_role_key
    headers = {"apikey": key, **({"Authorization": f"Bearer {key}"} if key.startswith("eyJ") else {})}

    users = httpx.get(f"{base}/auth/v1/admin/users", headers=headers, params={"per_page": 200}, timeout=30)
    users.raise_for_status()
    user = next((u for u in users.json().get("users", []) if (u.get("email") or "").lower() == email), None)
    if user is None:
        print(f"No dashboard account for {email}.")
        return 1

    pw = getpass.getpass(f"New password for {email} (min {MIN_LENGTH} chars): ")
    if len(pw) < MIN_LENGTH:
        print(f"Too short: use at least {MIN_LENGTH} characters.")
        return 1
    if getpass.getpass("Repeat password: ") != pw:
        print("Passwords don't match.")
        return 1

    r = httpx.put(f"{base}/auth/v1/admin/users/{user['id']}", headers=headers, json={"password": pw}, timeout=30)
    if r.status_code != 200:
        print(f"Failed: HTTP {r.status_code} {r.json().get('msg', '')}")
        return 1
    print("Password set. Sign in at the dashboard with your email and this password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
