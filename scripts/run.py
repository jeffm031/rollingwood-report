#!/usr/bin/env python3
"""
Rollingwood Report — automated meeting summarizer.

Pipeline:
  1. Check Rollingwood YouTube channel for new meeting videos
  2. Download audio (MP3) via yt-dlp
  3. Transcribe via AssemblyAI (with speaker diarization)
  4. Summarize via Claude Opus 4.7 using the locked prompt
  5. Save to Google Drive + email to Jeff
  6. Record meeting ID so we never re-process

Run locally:  python scripts/run.py
Run in CI:    triggered by .github/workflows/rollingwood.yml
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import assemblyai as aai
import yt_dlp
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import base64

load_dotenv(Path(__file__).parent.parent / ".env")

from pdf_export import derive_meeting_date, export_to_pdf, extract_meeting_type
import roster as _roster

# --- Config -----------------------------------------------------------------

CHANNEL_URL = "https://www.youtube.com/@cityofrollingwoodtexas/videos"
STATE_FILE = Path("processed_meetings.json")
PROMPT_FILE = Path("prompts/summary_prompt.md")
WORK_DIR = Path("workdir")
DRIVE_FOLDER_NAME = "Rollingwood Reports"
EMAIL_TO = "jeffm031@gmail.com"

# Only process videos whose title matches these (case-insensitive)
MEETING_TITLE_KEYWORDS = [
    "city council",
    "parks commission",
    "planning and zoning",
    "p&z",
    "rcdc",
    "community development corporation",
    "special meeting",
    "workshop",
]

CLAUDE_MODEL = "claude-opus-4-7"

# --- Secrets (from env) -----------------------------------------------------

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
ASSEMBLYAI_API_KEY = os.environ["ASSEMBLYAI_API_KEY"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDS_JSON"]  # OAuth token JSON


# --- Step 1: Discover new meetings ------------------------------------------

def list_recent_videos(max_videos: int = 5) -> list[dict]:
    """Return recent videos from the Rollingwood channel (newest first)."""
    opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": max_videos,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(CHANNEL_URL, download=False)
    entries = info.get("entries", []) or []
    videos = []
    for e in entries:
        videos.append({
            "id": e.get("id"),
            "title": e.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={e.get('id')}",
            "duration": e.get("duration"),
        })
    return videos


def is_meeting(title: str) -> bool:
    t = title.lower()
    return any(k in t for k in MEETING_TITLE_KEYWORDS)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"processed": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


# --- Step 2: Download audio --------------------------------------------------

def download_audio(video_url: str, video_id: str) -> Path:
    WORK_DIR.mkdir(exist_ok=True)
    out_template = str(WORK_DIR / f"{video_id}.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video_url])
    mp3 = WORK_DIR / f"{video_id}.mp3"
    if not mp3.exists():
        raise RuntimeError(f"Audio download failed for {video_id}")
    return mp3


# --- Step 3: Transcribe -----------------------------------------------------

def transcribe(audio_path: Path) -> str:
    """Return a speaker-labeled transcript."""
    aai.settings.api_key = ASSEMBLYAI_API_KEY
    config = aai.TranscriptionConfig(
        speaker_labels=True,
        punctuate=True,
        format_text=True,
        speech_models=["universal-3-pro"],
    )
    transcriber = aai.Transcriber(config=config)
    transcript = transcriber.transcribe(str(audio_path))
    if transcript.status == "error":
        raise RuntimeError(f"AssemblyAI error: {transcript.error}")

    lines = []
    if transcript.utterances:
        for u in transcript.utterances:
            ts = _format_hms(u.start)
            lines.append(f"({ts}) Speaker {u.speaker}: {u.text}")
    else:
        lines.append(transcript.text or "")
    return "\n\n".join(lines)


def _format_hms(ms: int) -> str:
    s = ms // 1000
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


# --- Step 4: Summarize with Claude ------------------------------------------

def summarize(transcript: str, video_title: str, video_url: str, video_id: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    system_prompt = PROMPT_FILE.read_text() + "\n\n" + _roster.format_for_prompt()
    user_content = (
        f"MEETING TITLE: {video_title}\n"
        f"YOUTUBE URL: {video_url}\n"
        f"VIDEO ID: {video_id}\n\n"
        f"TRANSCRIPT:\n\n{transcript}"
    )
    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=32000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        for _ in stream.text_stream:
            pass
        final = stream.get_final_message()
    if final.stop_reason == "max_tokens":
        print(
            f"⚠️  Warning: Claude hit the max_tokens ceiling (32000); summary may be truncated.",
            file=sys.stderr,
        )
    return "".join(b.text for b in final.content if b.type == "text")


# --- Step 5: Deliver (Drive + Gmail) ----------------------------------------

def google_services():
    creds = Credentials.from_authorized_user_info(json.loads(GOOGLE_CREDS_JSON))
    drive = build("drive", "v3", credentials=creds)
    gmail = build("gmail", "v1", credentials=creds)
    return drive, gmail


def get_or_create_drive_folder(drive, name: str) -> str:
    q = (
        f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    res = drive.files().list(q=q, fields="files(id,name)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    folder = drive.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder"},
        fields="id",
    ).execute()
    return folder["id"]


def upload_to_drive(drive, folder_id: str, filename: str, content: str) -> str:
    tmp = WORK_DIR / filename
    tmp.write_text(content)
    media = MediaFileUpload(str(tmp), mimetype="text/markdown")
    f = drive.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        fields="id,webViewLink",
    ).execute()
    return f["webViewLink"]


def send_email(
    gmail,
    subject: str,
    body_md: str,
    drive_link: str,
    pdf_link: str,
    pdf_path: Path,
) -> None:
    msg = MIMEMultipart("mixed")
    msg["to"] = EMAIL_TO
    msg["subject"] = subject
    text = (
        f"{body_md}\n\n---\n"
        f"PDF (attached and on Drive): {pdf_link}\n"
        f"Markdown + transcript: {drive_link}\n"
    )
    msg.attach(MIMEText(text, "plain"))
    with open(pdf_path, "rb") as f:
        attach = MIMEBase("application", "pdf")
        attach.set_payload(f.read())
    encoders.encode_base64(attach)
    attach.add_header(
        "Content-Disposition", f'attachment; filename="{pdf_path.name}"'
    )
    msg.attach(attach)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    gmail.users().messages().send(userId="me", body={"raw": raw}).execute()


# --- Main -------------------------------------------------------------------

def main() -> int:
    state = load_state()
    processed = state["processed"]

    print("🔍 Checking Rollingwood YouTube channel...")
    videos = list_recent_videos(max_videos=5)
    new_meetings = [
        v for v in videos
        if v["id"] not in processed and is_meeting(v["title"])
    ]

    if not new_meetings:
        print("✅ No new meetings to process.")
        return 0

    # Process oldest-first so emails arrive in order
    new_meetings.reverse()
    drive, gmail = google_services()
    folder_id = get_or_create_drive_folder(drive, DRIVE_FOLDER_NAME)

    for v in new_meetings:
        print(f"\n📼 Processing: {v['title']} ({v['id']})")
        try:
            audio = download_audio(v["url"], v["id"])
            print(f"   ↳ audio: {audio.name} ({audio.stat().st_size // 1024} KB)")

            print("   ↳ transcribing with AssemblyAI...")
            transcript = transcribe(audio)
            print(f"   ↳ transcript: {len(transcript)} chars")

            print("   ↳ summarizing with Claude Opus 4.7...")
            summary = summarize(transcript, v["title"], v["url"], v["id"])

            stamp = datetime.now().strftime("%Y-%m-%d")
            filename = f"{stamp} — {v['title']}.md".replace("/", "-")

            # Save full transcript alongside summary
            full_doc = (
                f"# {v['title']}\n\n"
                f"**YouTube:** {v['url']}\n"
                f"**Processed:** {stamp}\n\n"
                f"---\n\n"
                f"{summary}\n\n"
                f"---\n\n"
                f"## Full Transcript\n\n{transcript}\n"
            )
            link = upload_to_drive(drive, folder_id, filename, full_doc)
            print(f"   ↳ drive (md):  {link}")

            pdf_filename = filename[:-3] + ".pdf"
            pdf_path = WORK_DIR / pdf_filename
            meeting_type = extract_meeting_type(summary, fallback=v["title"])
            meeting_date = derive_meeting_date(v["title"], fallback=stamp)
            export_to_pdf(summary, pdf_path, meeting_type, meeting_date)
            pdf_media = MediaFileUpload(str(pdf_path), mimetype="application/pdf")
            pdf_file = drive.files().create(
                body={"name": pdf_filename, "parents": [folder_id]},
                media_body=pdf_media,
                fields="id,webViewLink",
            ).execute()
            pdf_link = pdf_file["webViewLink"]
            print(f"   ↳ drive (pdf): {pdf_link}")

            send_email(
                gmail,
                subject=f"Rollingwood Report: {meeting_type} — {meeting_date}",
                body_md=summary,
                drive_link=link,
                pdf_link=pdf_link,
                pdf_path=pdf_path,
            )
            print("   ↳ email sent ✉️")

            processed[v["id"]] = {
                "title": v["title"],
                "processed_at": stamp,
                "drive_link": link,
            }
            save_state(state)

            # Cleanup audio to save repo space
            audio.unlink(missing_ok=True)

        except Exception as e:
            print(f"   ❌ Error: {e}", file=sys.stderr)
            # Don't block other meetings; log and continue
            continue

    print("\n✅ Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
