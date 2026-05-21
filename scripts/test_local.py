#!/usr/bin/env python3
"""
Local test — run the transcribe + summarize pipeline on an MP4 you already have.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export ASSEMBLYAI_API_KEY=...
    python scripts/test_local.py "/Users/jeffmarx/Special City Council Meeting 4-14-2026 [ecUUdeLa5_A].mp4"

Optional --packet accepts a URL or local PDF path; its extracted text is
prepended to the model input ahead of the transcript so the summary can
ground itself in the scheduled agenda items (the recording is still
authoritative for what actually happened).

Output:
    - Transcript saved next to the input as .transcript.txt (cached)
    - Summary saved next to the input as .summary.md
    - PDF saved as .summary.pdf — SKIPPED if Claude truncated the summary,
      in which case the script exits with code 3 (EXIT_TRUNCATED)
"""

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import anthropic
import assemblyai as aai
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from pdf_export import derive_meeting_date, export_to_pdf, extract_meeting_type
import roster as _roster
from scrape_tier2 import CACHE_DIR, cached_packet_bytes, extract_text

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "summary_prompt.md"
CLAUDE_MODEL = "claude-opus-4-7"

# main() exit code when Claude truncated the summary (stop_reason == max_tokens).
# Distinct from 1 (usage / file errors) so automation can detect truncation.
EXIT_TRUNCATED = 3


def _format_hms(ms: int) -> str:
    s = ms // 1000
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


def transcribe(audio_path: Path) -> str:
    print(f"🎙️  Transcribing {audio_path.name} with AssemblyAI...")
    print("    (this takes roughly real-time-÷-3, so a 2hr meeting ≈ 6-8 min)")
    aai.settings.api_key = os.environ["ASSEMBLYAI_API_KEY"]
    # A long meeting's completed-transcript JSON is multi-MB; the SDK default
    # HTTP timeout is too short to fetch it and raises httpx.ReadTimeout
    # mid-poll. 600 s leaves generous headroom.
    aai.settings.http_timeout = 600
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


def _ocr_pdf_bytes(pdf_bytes: bytes) -> str:
    """OCR pdf_bytes via ocrmypdf; return extracted text. Cached by content SHA1.

    Called when extract_text returned no text (image-only PDF). The OCR result
    is cached as ``data/packet_cache/<sha1>.ocr.txt`` keyed off the PDF's
    content hash, so re-running with the same input (URL or local file) skips
    the OCR pass. Returns ``""`` if ocrmypdf is missing, errors, times out, or
    yields empty text; the caller is expected to warn-and-continue.
    """
    key = hashlib.sha1(pdf_bytes).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sidecar = CACHE_DIR / f"{key}.ocr.txt"
    if sidecar.exists():
        cached = sidecar.read_text()
        print(f"   ↳ OCR cached: {sidecar.name} ({len(cached):,} chars)")
        return cached

    print("🔎 Empty text layer; running OCR (ocrmypdf) — this may take 30s+...")
    try:
        with tempfile.TemporaryDirectory() as td:
            in_path = Path(td) / "input.pdf"
            out_path = Path(td) / "ocr.pdf"
            tmp_sidecar = Path(td) / "ocr.txt"
            in_path.write_bytes(pdf_bytes)
            subprocess.run(
                ["ocrmypdf", "--force-ocr", "--sidecar", str(tmp_sidecar),
                 str(in_path), str(out_path)],
                check=True, capture_output=True, timeout=600,
            )
            ocr_text = tmp_sidecar.read_text() if tmp_sidecar.exists() else ""
    except FileNotFoundError:
        print(
            "⚠️  ocrmypdf not installed (brew install ocrmypdf); "
            "continuing without packet.",
            file=sys.stderr,
        )
        return ""
    except subprocess.CalledProcessError as e:
        stderr_tail = (e.stderr or b"").decode(errors="replace")[-400:]
        print(
            f"⚠️  ocrmypdf failed (exit {e.returncode}); continuing without packet.\n"
            f"    stderr tail: {stderr_tail}",
            file=sys.stderr,
        )
        return ""
    except subprocess.TimeoutExpired:
        print(
            "⚠️  ocrmypdf timed out (>10 min); continuing without packet.",
            file=sys.stderr,
        )
        return ""
    except Exception as e:
        print(
            f"⚠️  OCR failed ({type(e).__name__}: {e}); continuing without packet.",
            file=sys.stderr,
        )
        return ""

    if not ocr_text.strip():
        print(
            "⚠️  OCR yielded empty text; continuing without packet.",
            file=sys.stderr,
        )
        return ""

    sidecar.write_text(ocr_text)
    print(f"   ↳ OCR text: {len(ocr_text):,} chars (cached to {sidecar.name})")
    return ocr_text


def load_packet_text(packet_arg: str) -> str:
    """Fetch (URL) or read (local path) a packet PDF and return its text.

    Reuses ``scrape_tier2.cached_packet_bytes`` for URLs (so repeat runs hit
    the same ``data/packet_cache/`` the Tier 2 scraper uses) and
    ``scrape_tier2.extract_text`` for PDF→text. Returns ``""`` on any
    failure — the caller is expected to warn and continue without a packet
    rather than aborting the run.
    """
    if packet_arg.startswith(("http://", "https://")):
        print(f"📎 Fetching agenda packet: {packet_arg}")
        try:
            pdf_bytes = cached_packet_bytes(packet_arg)
        except Exception as e:
            print(
                f"⚠️  Packet download failed ({e}); continuing without packet.",
                file=sys.stderr,
            )
            return ""
    else:
        packet_path = Path(packet_arg).expanduser()
        if not packet_path.exists():
            print(
                f"⚠️  Packet file not found: {packet_path}; continuing without packet.",
                file=sys.stderr,
            )
            return ""
        print(f"📎 Reading agenda packet: {packet_path.name}")
        pdf_bytes = packet_path.read_bytes()
    text = extract_text(pdf_bytes)
    if not text.strip():
        # Image-only PDF (e.g. Rollingwood agenda PDFs). Try OCR before bailing.
        text = _ocr_pdf_bytes(pdf_bytes)
        if not text.strip():
            return ""  # _ocr_pdf_bytes already printed the failure warning
    print(f"   ↳ packet text: {len(text):,} chars")
    return text


def summarize(
    transcript: str,
    meeting_title: str,
    video_id: str = "",
    packet_text: str = "",
) -> tuple[str, str]:
    """Summarize the transcript with Claude.

    Returns ``(summary_text, stop_reason)``. A ``stop_reason`` of
    ``"max_tokens"`` means Claude hit the output ceiling and the summary is
    truncated; the caller decides what to do — ``main()`` writes the partial
    ``.md`` for inspection but skips PDF export and exits ``EXIT_TRUNCATED``.
    """
    print(f"🧠 Summarizing with Claude {CLAUDE_MODEL}...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = PROMPT_FILE.read_text() + "\n\n" + _roster.format_for_prompt()
    packet_block = ""
    if packet_text:
        packet_block = (
            "=== AGENDA PACKET (scheduled items; the recording is authoritative "
            "for what actually occurred) ===\n"
            f"{packet_text}\n"
            "=== END AGENDA PACKET ===\n\n"
        )
    user_content = (
        packet_block
        + f"MEETING TITLE: {meeting_title}\n"
        + (f"VIDEO ID: {video_id}\n\n" if video_id else "\n")
        + f"TRANSCRIPT:\n\n{transcript}"
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
    summary = "".join(b.text for b in final.content if b.type == "text")
    # Safety net: the prompt asks Claude to substitute the VIDEO ID field for
    # the literal `VIDEO_ID` token in citation URLs. If it copies the token
    # verbatim instead, every timestamp link breaks — so substitute
    # deterministically here. A correct model run leaves nothing to replace.
    if video_id:
        summary = summary.replace("VIDEO_ID", video_id)
    return summary, final.stop_reason


def main():
    ap = argparse.ArgumentParser(
        description="Transcribe + summarize a meeting recording locally."
    )
    ap.add_argument("audio", help="Path to the meeting MP4/MP3.")
    ap.add_argument(
        "--packet",
        default=None,
        help=(
            "Optional URL or local path to the meeting's agenda packet PDF. "
            "When present, its extracted text is prepended to the model input "
            "ahead of the transcript. Failures (download error, missing file, "
            "or empty text) warn and continue without the packet."
        ),
    )
    args = ap.parse_args()

    audio_path = Path(args.audio).expanduser()
    if not audio_path.exists():
        print(f"❌ File not found: {audio_path}")
        sys.exit(1)

    packet_text = load_packet_text(args.packet) if args.packet else ""

    # Cache transcript so re-runs skip the expensive step
    transcript_path = audio_path.with_suffix(audio_path.suffix + ".transcript.txt")
    summary_path = audio_path.with_suffix(audio_path.suffix + ".summary.md")

    if transcript_path.exists():
        print(f"📄 Using cached transcript: {transcript_path.name}")
        transcript = transcript_path.read_text()
    else:
        transcript = transcribe(audio_path)
        transcript_path.write_text(transcript)
        print(f"   ↳ saved: {transcript_path.name}")

    stem = audio_path.stem
    if " [" in stem and stem.endswith("]"):
        meeting_title, video_id = stem.rsplit(" [", 1)
        video_id = video_id[:-1]
    else:
        meeting_title, video_id = stem, ""
        print(
            f"⚠️  No '[<video id>]' bracket in filename '{audio_path.name}' — "
            f"timestamp citation links will be omitted from the summary. "
            f"Rename the file to '<title> [<youtube id>].<ext>' to enable "
            f"verifiable links.",
            file=sys.stderr,
        )
    summary, stop_reason = summarize(transcript, meeting_title, video_id, packet_text)
    # Write the .md unconditionally — even a truncated summary should be
    # inspectable so the operator can decide whether to keep it or re-run.
    summary_path.write_text(summary)
    print(f"\n✅ Summary saved: {summary_path}")

    if stop_reason == "max_tokens":
        print(
            "\n⚠️  TRUNCATED: Claude hit the max_tokens ceiling (32000); the "
            "summary is incomplete.\n"
            f"    The partial summary was written to {summary_path.name} for "
            "inspection,\n"
            "    but PDF export was SKIPPED so a truncated report is never "
            "published.\n"
            "    Re-run to retry — the cached transcript means AssemblyAI is "
            "not re-charged.",
            file=sys.stderr,
        )
        sys.exit(EXIT_TRUNCATED)

    pdf_path = summary_path.with_suffix(".pdf")
    meeting_type = extract_meeting_type(summary)
    meeting_date = derive_meeting_date(audio_path.name, fallback="")
    export_to_pdf(summary, pdf_path, meeting_type, meeting_date)
    print(f"📄 PDF saved: {pdf_path}")

    print("=" * 70)
    print(summary)
    print("=" * 70)


if __name__ == "__main__":
    main()
