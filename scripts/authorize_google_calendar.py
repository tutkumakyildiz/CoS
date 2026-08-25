"""One-time local script to obtain GOOGLE_REFRESH_TOKEN for the calendar_tool.

Not imported by any runtime code path — this only ever runs by hand, once,
on a machine with a browser. The deployed bot runs headless (Bedrock
AgentCore Runtime) and can't do interactive OAuth consent itself, so this
script does it once locally and hands you the resulting long-lived refresh
token to paste into .env (local dev) and
deploy/agentcore-runtime-create-request.json's environmentVariables
(deployed brain).

Requires the "calendar" extra: pip install -e ".[calendar]"

Usage:
    GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python scripts/authorize_google_calendar.py

See README "Google Calendar setup" for how to get a client id/secret from
Google Cloud Console first (OAuth consent screen + a "Desktop app" credential).
"""

from __future__ import annotations

import os
import sys

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def main() -> None:
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print('Missing dependency. Run: pip install -e ".[calendar]"', file=sys.stderr)
        raise SystemExit(1)

    client_id = os.environ.get("GOOGLE_CLIENT_ID") or input("GOOGLE_CLIENT_ID: ").strip()
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or input("GOOGLE_CLIENT_SECRET: ").strip()

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    print("Opening a browser to sign in and grant calendar access...")
    # access_type="offline" is what makes Google issue a refresh token at all
    # (default is online-only, access-token-only). prompt="consent" forces the
    # consent screen (and a fresh refresh token) even if this account already
    # granted access before — otherwise a repeat run silently returns none.
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not credentials.refresh_token:
        print(
            "No refresh token was returned. This usually means you've already granted "
            "this app access before — go to https://myaccount.google.com/permissions, "
            "remove its access, and run this script again so Google issues a new one.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("\nSuccess. Add these to .env (local dev) and to")
    print("deploy/agentcore-runtime-create-request.json's environmentVariables (deployed brain):\n")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={credentials.refresh_token}")


if __name__ == "__main__":
    main()
