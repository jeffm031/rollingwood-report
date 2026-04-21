#!/usr/bin/env python3
"""Send a preview email from a summary markdown file.

Reads a .summary.md file, renders the markdown to HTML (YouTube timestamp
links preserved as clickable), assembles a multipart/alternative message
with plain-text fallback, and either prints it to stdout (--dry-run,
default) or sends it via the Gmail API (--send).

Token is loaded from token_newsletter.json at the project root — the
OAuth consent there is bound to rollingwoodreport@gmail.com, so the
send is FROM that address regardless of who runs the script. Recipient
is passed explicitly via --to; no subscriber list is consulted.

Usage:
  # Dry-run — inspect the rendered email without sending
  python scripts/send_preview.py /path/to/summary.md --to you@example.com

  # Actually send
  python scripts/send_preview.py /path/to/summary.md --to you@example.com --send

Scope (2026-04-21): preview / proof-of-concept only. Single recipient per
invocation, no subscriber handling, no preference segmentation, no reply
tracking. Template polish, list handling, and feedback-loop wiring come
later.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import markdown
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ROOT = Path(__file__).parent.parent
TOKEN_FILE = ROOT / "token_newsletter.json"

# Light inline styling applied to the HTML body. Gmail strips <style> blocks
# and external stylesheets; inline styles on the <body> wrapper reliably
# survive. Intentionally minimal — font, max-width, line-height.
BODY_WRAPPER_STYLE = (
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', "
    "Roboto, Helvetica, Arial, sans-serif; "
    "max-width: 680px; margin: 0 auto; padding: 16px; "
    "line-height: 1.5; color: #222;"
)


def load_gmail_service():
    if not TOKEN_FILE.exists():
        raise SystemExit(
            f"Missing {TOKEN_FILE}. Run "
            "scripts/bootstrap_google_auth_newsletter.py first."
        )
    creds = Credentials.from_authorized_user_info(
        json.loads(TOKEN_FILE.read_text())
    )
    return build("gmail", "v1", credentials=creds)


def derive_subject(body_md: str, fallback_path: Path) -> str:
    """Pull the first H1 from the markdown body; else derive from filename.

    Fallback strategy: the summary pipeline names files
    `<meeting title> <M-D-YYYY> [<video id>].<ext>.summary.md`. Strip the
    doubled extension and the `[video id]` bracket, then if a `M-D-YYYY`
    date is present, normalize it to ISO and build
    `Rollingwood Report: <title> — <YYYY-MM-DD>`. If no date pattern
    matches, return the cleaned stem verbatim.
    """
    for raw in body_md.splitlines():
        line = raw.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()

    stem = fallback_path.name
    if stem.endswith(".md"):
        stem = stem[:-3]
    if stem.endswith(".summary"):
        stem = stem[: -len(".summary")]
    if stem.endswith(".mp3") or stem.endswith(".mp4"):
        stem = stem[:-4]
    stem = re.sub(r"\s*\[[^\]]+\]\s*$", "", stem).strip()

    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", stem)
    if m:
        month, day, year = m.groups()
        iso = f"{year}-{int(month):02d}-{int(day):02d}"
        before = stem[: m.start()].strip()
        if before:
            return f"Rollingwood Report: {before} — {iso}"
        return f"Rollingwood Report — {iso}"
    return stem or fallback_path.stem


def render_html(body_md: str) -> str:
    """Render markdown to HTML, wrap in a minimal styled <body>.

    Uses the `extra` extension (tables, fenced code, footnotes, attr_list,
    etc.) and `sane_lists` so multi-line bullets don't collapse. `nl2br`
    is NOT enabled — the summaries use paragraph breaks intentionally and
    hard-line-breaks would inflate the rendering.
    """
    html_body = markdown.markdown(
        body_md, extensions=["extra", "sane_lists"]
    )
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n"
        '  <meta charset="utf-8">\n</head>\n'
        f'<body style="{BODY_WRAPPER_STYLE}">\n'
        f"{html_body}\n</body>\n</html>\n"
    )


def build_message(subject: str, to_addr: str, body_md: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["to"] = to_addr
    msg["subject"] = subject
    msg.attach(MIMEText(body_md, "plain", "utf-8"))
    msg.attach(MIMEText(render_html(body_md), "html", "utf-8"))
    return msg


def _truncate_lines(lines: list, cap: int, label: str) -> list:
    if len(lines) <= cap:
        return lines
    return lines[:cap] + [f"... [{len(lines) - cap} more {label}]"]


def print_dry_run(
    subject: str,
    sender: str,
    to_addr: str,
    body_md: str,
    html: str,
) -> None:
    print("=== DRY-RUN — email assembled, not sent ===")
    print(f"From:    {sender}")
    print(f"To:      {to_addr}")
    print(f"Subject: {subject}")
    print()
    print("--- Plain-text body (first 40 lines) ---")
    for line in _truncate_lines(body_md.splitlines(), 40, "lines"):
        print(line)
    print()
    print("--- HTML body (first 60 lines of rendered HTML) ---")
    for line in _truncate_lines(html.splitlines(), 60, "lines"):
        print(line)
    print()
    print("(pass --send to actually send)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Send a preview email from a summary markdown file."
    )
    ap.add_argument(
        "summary_path", type=Path, help="Path to a .summary.md file."
    )
    ap.add_argument(
        "--to", required=True, help="Recipient email address."
    )
    ap.add_argument(
        "--send", action="store_true",
        help="Actually send via Gmail API. Default is dry-run (print to stdout).",
    )
    args = ap.parse_args()

    if not args.summary_path.exists():
        print(f"Summary file not found: {args.summary_path}", file=sys.stderr)
        return 1

    body_md = args.summary_path.read_text()
    subject = derive_subject(body_md, fallback_path=args.summary_path)
    html = render_html(body_md)

    if not args.send:
        # Dry-run doesn't need to hit the network; sender address is reported
        # as the token's declared identity, surfaced from the profile only on
        # --send (to avoid a needless API call on every dry-run).
        print_dry_run(
            subject=subject,
            sender="rollingwoodreport@gmail.com (token_newsletter.json)",
            to_addr=args.to,
            body_md=body_md,
            html=html,
        )
        return 0

    gmail = load_gmail_service()
    profile = gmail.users().getProfile(userId="me").execute()
    sender = profile.get("emailAddress", "(unknown)")
    print(f"Authenticated as: {sender}")
    print(f"Sending to:       {args.to}")
    print(f"Subject:          {subject}")

    msg = build_message(subject, args.to, body_md)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = gmail.users().messages().send(
        userId="me", body={"raw": raw},
    ).execute()
    print(f"Sent. Gmail message id: {result.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
