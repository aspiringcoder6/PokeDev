"""Mint a TTeamFlow browser session file and a fixture API token.

TTeamFlow keeps the SPA logged in through an httpOnly refresh cookie
(path /api/v1/auth) and authenticates API calls with a short-lived (15m)
Bearer access token held in memory. This script performs one real login and:

- writes a Playwright storageState JSON containing the refresh cookie so a
  browser context restores the session via the app's own /auth/refresh bootstrap
- writes "Bearer <accessToken>" to a text file for STAGING_TTEAMFLOW_FIXTURE_AUTH
- verifies the access token against GET /auth/me before writing anything

Secrets are written only to the paths you pass; token values are never printed.

PowerShell (run TTeamFlow dev servers first):
  python scripts/tteamflow_session.py --email admin@example.com --password '...' `
    --state-out config/tteamflow.admin.state.json --token-out config/tteamflow.fixture.token.txt
  $env:STAGING_TTEAMFLOW_ADMIN_STATE = (Resolve-Path config/tteamflow.admin.state.json).Path
  $env:STAGING_TTEAMFLOW_FIXTURE_AUTH = (Get-Content config/tteamflow.fixture.token.txt -Raw).Trim()
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib import request as urlrequest
from urllib.parse import urlsplit


def _post_json(url, body, headers=None):
    req = urlrequest.Request(url, data=json.dumps(body).encode(), method="POST",
                             headers={"Content-Type": "application/json", **(headers or {})})
    with urlrequest.urlopen(req, timeout=30) as response:
        return json.loads(response.read()), response.headers.get_all("Set-Cookie") or []


def _refresh_cookie(cookies):
    for header in cookies:
        if "refresh_token=" in header:
            raw = header.split("refresh_token=", 1)[1].split(";", 1)[0]
            attributes = {}
            for part in header.split(";")[1:]:
                if "=" in part:
                    key, value = part.strip().split("=", 1)
                    attributes[key.lower()] = value
            return raw, attributes.get("path", "/")
    raise SystemExit("Login response did not set a refresh_token cookie")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:3000/api/v1")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--state-out", required=True)
    parser.add_argument("--token-out", required=True)
    args = parser.parse_args()

    payload, cookies = _post_json(args.api_url.rstrip("/") + "/auth/login",
                                  {"email": args.email, "password": args.password})
    data = payload.get("data") or {}
    token = data.get("accessToken")
    if payload.get("success") is not True or not token:
        raise SystemExit("Login failed: unexpected response payload")

    req = urlrequest.Request(args.api_url.rstrip("/") + "/auth/me",
                             headers={"Authorization": f"Bearer {token}"})
    with urlrequest.urlopen(req, timeout=30) as response:
        me = json.loads(response.read())
    if (me.get("data") or {}).get("email") != (data.get("user") or {}).get("email"):
        raise SystemExit("Identity check failed: /auth/me mismatch")

    raw, path = _refresh_cookie(cookies)
    state = {
        "cookies": [{
            "name": "refresh_token", "value": raw, "domain": urlsplit(args.api_url).hostname,
            "path": path, "expires": time.time() + 7 * 24 * 3600,
            "httpOnly": True, "secure": False, "sameSite": "Lax",
        }],
        "origins": [],
    }
    state_path = Path(args.state_out)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    token_path = Path(args.token_out)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(f"Bearer {token}\n", encoding="utf-8")

    print(f"storageState written: {state_path}")
    print(f"fixture token written (valid ~15 minutes): {token_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
