#!/usr/bin/env python3
"""
Local test — run the transcribe + summarize pipeline on an MP4 you already have.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export ASSEMBLYAI_API_KEY=...
    python scripts/test_local.py "/Users/jeffmarx/Special City Council Meeting 4-14-2026 [ecUUdeLa5_A].mp4"

Output:
    - Transcript saved next to the MP4 as .transcript.txt
    - Summary saved next to the MP4 as .summary.md
    - Both printed to terminal
"""

import os
import sys
from pathlib import Path

import anthropic
import assemblyai as aai
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from pdf_export import derive_meeting_date, export_to_pdf, extract_meeting_type
import roster as _roster

PROMPT_FILE = Path(__file__).parent.parent / "prompts" / "summary_prompt.md"
CLAUDE_MODEL = "claude-opus-4-7"


def _format_hms(ms: int) -> str:
    s = ms // 1000
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}"


def transcribe(audio_path: Path) -> str:
    print(f"🎙️  Transcribing {audio_path.name} with AssemblyAI...")
    print("    (this takes roughly real-time-÷-3, so a 2hr meeting ≈ 6-8 min)")
    aai.settings.api_key = os.environ["ASSEMBLYAI_API_KEY"]
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


def summarize(transcript: str, meeting_title: str, video_id: str = "") -> str:
    print(f"🧠 Summarizing with Claude {CLAUDE_MODEL}...")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system_prompt = PROMPT_FILE.read_text() + "\n\n" + _roster.format_for_prompt()
    user_content = (
        f"MEETING TITLE: {meeting_title}\n"
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
    if final.stop_reason == "max_tokens":
        print(
            f"⚠️  Warning: Claude hit the max_tokens ceiling (32000); summary may be truncated.",
            file=sys.stderr,
        )
    return "".join(b.text for b in final.content if b.type == "text")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_local.py <path-to-mp4-or-mp3>")
        sys.exit(1)

    audio_path = Path(sys.argv[1]).expanduser()
    if not audio_path.exists():
        print(f"❌ File not found: {audio_path}")
        sys.exit(1)

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
    summary = summarize(transcript, meeting_title, video_id)
    summary_path.write_text(summary)

    pdf_path = summary_path.with_suffix(".pdf")
    meeting_type = extract_meeting_type(summary)
    meeting_date = derive_meeting_date(audio_path.name, fallback="")
    export_to_pdf(summary, pdf_path, meeting_type, meeting_date)
    print(f"📄 PDF saved: {pdf_path}")

    print(f"\n✅ Summary saved: {summary_path}\n")
    print("=" * 70)
    print(summary)
    print("=" * 70)


if __name__ == "__main__":
    main()
