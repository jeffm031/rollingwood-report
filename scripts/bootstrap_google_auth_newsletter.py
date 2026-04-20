#!/usr/bin/env python3
"""
Bootstrap the newsletter-account OAuth token (rollingwoodreport@gmail.com).

Run this ONCE locally. Before running:
  1. Place client_secret_newsletter.json in the repo root (OAuth client for the
     newsletter Google Cloud project, Desktop app credentials).
  2. Run: python scripts/bootstrap_google_auth_newsletter.py
  3. Browser opens → sign in AS rollingwoodreport@gmail.com → grant scopes.
  4. Token is saved locally to token_newsletter.json (gitignored).
  5. Copy the printed JSON blob into GitHub secret GOOGLE_CREDS_JSON_NEWSLETTER.
"""

from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

REPO_ROOT = Path(__file__).parent.parent
CLIENT_SECRET = REPO_ROOT / "client_secret_newsletter.json"
TOKEN_FILE = REPO_ROOT / "token_newsletter.json"


def main():
    if not CLIENT_SECRET.exists():
        raise SystemExit(
            f"Missing {CLIENT_SECRET.name} — download the OAuth client JSON "
            "for the newsletter project first."
        )

    print(
        "🔐 Opening browser for OAuth consent.\n"
        "   Sign in AS rollingwoodreport@gmail.com and approve all requested scopes.\n"
    )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    blob = creds.to_json()

    TOKEN_FILE.write_text(blob)
    print(f"✅ Token saved locally: {TOKEN_FILE}")

    print("\n=== COPY EVERYTHING BELOW INTO GITHUB SECRET: GOOGLE_CREDS_JSON_NEWSLETTER ===\n")
    print(blob)
    print("\n=== END ===\n")

    # Smoke test — confirm the token can hit Gmail on the newsletter account.
    print("🧪 Smoke test: listing Gmail labels on rollingwoodreport@gmail.com…")
    gmail = build("gmail", "v1", credentials=creds)
    profile = gmail.users().getProfile(userId="me").execute()
    print(f"   Authenticated as: {profile.get('emailAddress')}")

    resp = gmail.users().labels().list(userId="me").execute()
    labels = resp.get("labels", [])
    print(f"   Found {len(labels)} label(s):")
    for lab in sorted(labels, key=lambda x: (x.get("type", ""), x.get("name", ""))):
        print(f"     - [{lab.get('type', '?')}] {lab.get('name', '?')}")


if __name__ == "__main__":
    main()
