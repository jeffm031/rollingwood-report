#!/usr/bin/env python3
"""
Run this ONCE on your Mac to generate the Google OAuth token.

Steps before running:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or reuse one)
  3. Enable: Google Drive API, Gmail API
  4. APIs & Services → Credentials → Create OAuth client ID → Desktop app
  5. Download the JSON as `client_secret.json` into this folder
  6. Run: python scripts/bootstrap_google_auth.py
  7. It opens a browser → sign in as jeffm031@gmail.com → grant access
  8. Copy the printed JSON blob into your GitHub repo secret `GOOGLE_CREDS_JSON`
"""

import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",      # create/manage files the app makes
    "https://www.googleapis.com/auth/gmail.send",      # send email as you
]

CLIENT_SECRET = Path("client_secret.json")

def main():
    if not CLIENT_SECRET.exists():
        raise SystemExit("Missing client_secret.json — download from Google Cloud Console first.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    blob = creds.to_json()
    print("\n\n=== COPY EVERYTHING BELOW INTO GITHUB SECRET: GOOGLE_CREDS_JSON ===\n")
    print(blob)
    print("\n=== END ===\n")

if __name__ == "__main__":
    main()
