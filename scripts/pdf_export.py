"""Render a summary markdown file to a newsletter-style PDF via WeasyPrint."""

import html
import re
from datetime import date
from pathlib import Path

import markdown
from weasyprint import CSS, HTML


_CSS = """
@page {
    size: letter;
    margin: 0.9in 0.85in 1in 0.85in;
    @bottom-center {
        content: "The Rollingwood Report — " string(meetingdate)
                 " — Page " counter(page) " of " counter(pages);
        font-family: 'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif;
        font-size: 8.5pt;
        color: #6a6a6a;
    }
}
@page :first {
    margin-bottom: 1.45in;
    @bottom-center {
        content: element(prepnote);
    }
}

body {
    font-family: 'Charter', Georgia, 'DejaVu Serif', 'Liberation Serif', serif;
    font-size: 10.5pt;
    line-height: 1.55;
    color: #1a1a1a;
}

/* -- Masthead (page 1 only, inline at top of body) ---------------------- */
.masthead {
    margin: 0 0 8pt 0;
    padding: 0;
}
.masthead-title {
    font-family: 'Didot', 'Bodoni 72', 'Playfair Display', 'Charter', Georgia, serif;
    font-weight: 700;
    font-size: 34pt;
    letter-spacing: 2pt;
    text-align: center;
    color: #111;
    margin: 0;
    line-height: 1;
}
.masthead-rule {
    border: 0;
    border-top: 1pt solid #111;
    margin: 10pt 0 8pt 0;
}
.masthead-sub {
    font-family: 'Charter', Georgia, serif;
    font-style: italic;
    font-size: 10pt;
    text-align: center;
    color: #333;
    margin: 0 0 10pt 0;
}
.masthead-issue {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 10pt;
    text-align: right;
    color: #1f3a5f;
    font-weight: 600;
    margin: 0;
}
.masthead-byline {
    font-family: 'Charter', Georgia, serif;
    font-style: italic;
    font-size: 9pt;
    text-align: right;
    color: #555;
    margin: 2pt 0 18pt 0;
}
.masthead-bottom-rule {
    border: 0;
    border-top: 0.5pt solid #bbb;
    margin: 0 0 14pt 0;
}

/* -- Prep note callout (runs in page 1 bottom margin) ------------------- */
.prep-note {
    position: running(prepnote);
    border: 0.5pt solid #b5b5b5;
    background: #fafafa;
    padding: 7pt 10pt;
    font-family: 'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif;
    font-size: 8.25pt;
    line-height: 1.4;
    color: #444;
    width: 100%;
    box-sizing: border-box;
}
.prep-note strong {
    font-family: 'Charter', Georgia, serif;
    font-weight: 700;
    color: #1f3a5f;
}

/* -- Body content ------------------------------------------------------- */
h1, h2 {
    font-family: 'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif;
    font-weight: 700;
    font-size: 13.5pt;
    color: #1f3a5f;
    margin: 18pt 0 6pt;
    letter-spacing: 0.2pt;
    page-break-after: avoid;
}
h2 {
    border-bottom: 0.5pt solid #d4dae3;
    padding-bottom: 3pt;
}
h3 {
    font-family: 'Helvetica Neue', Arial, 'DejaVu Sans', sans-serif;
    font-weight: 700;
    font-size: 11.5pt;
    color: #2a2a2a;
    margin: 13pt 0 3pt;
    page-break-after: avoid;
}
p {
    margin: 5pt 0;
    font-size: 10.5pt;
    line-height: 1.55;
}
ul, ol {
    padding-left: 18pt;
    margin: 5pt 0;
}
li {
    margin-bottom: 3pt;
    font-size: 10.5pt;
    line-height: 1.5;
}
strong { color: #111; }
em { color: #2a2a2a; }

table {
    border-collapse: collapse;
    width: 100%;
    margin: 8pt 0;
    font-size: 9.5pt;
    page-break-inside: avoid;
}
th, td {
    border: 0.5pt solid #bcbcbc;
    padding: 4pt 6pt;
    text-align: left;
    vertical-align: top;
    line-height: 1.4;
}
th {
    background: #eef1f5;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-weight: 600;
    color: #1f3a5f;
}

blockquote {
    border-left: 2pt solid #c9d0d9;
    padding-left: 10pt;
    color: #3a3a3a;
    font-style: italic;
    margin: 8pt 0;
}
code {
    font-family: 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace;
    font-size: 9.5pt;
    background: #f4f4f4;
    padding: 1pt 3pt;
}
"""


_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{issue_title}</title></head>
<body>
<div class="masthead">
  <div class="masthead-title">THE ROLLINGWOOD REPORT</div>
  <hr class="masthead-rule" />
  <div class="masthead-sub">An independent summary of Rollingwood municipal meetings</div>
  <div class="masthead-issue">Issue: {issue_title}</div>
  <div class="masthead-byline">Compiled by Jeff Marx, Rollingwood resident</div>
  <hr class="masthead-bottom-rule" />
</div>
<div class="prep-note" id="prepnote-elem">
  <strong>How this report is prepared.</strong> This report is compiled from the
  public recording of the meeting using AI-assisted transcription and
  summarization. Errors are possible; the official record is the City's archived
  video. Feedback: jeffm031@gmail.com
</div>
<span style="string-set: meetingdate '{meeting_date}'"></span>
{body}
</body>
</html>
"""


_YMD = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_MDY = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b")
_MEETING_TYPE_RE = re.compile(
    r"^[-*]\s*\*\*Meeting\s+type:\*\*\s*([^\n(]+?)(?:\s*\(|\s*$)", re.MULTILINE
)


def derive_meeting_date(source: str, fallback: str = "") -> str:
    """Extract a human-readable date from a filename or title (YYYY-MM-DD or M/D/YYYY)."""
    m = _YMD.search(source)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.strftime("%B %-d, %Y")
        except ValueError:
            pass
    m = _MDY.search(source)
    if m:
        year = int(m.group(3))
        if year < 100:
            year += 2000
        try:
            d = date(year, int(m.group(1)), int(m.group(2)))
            return d.strftime("%B %-d, %Y")
        except ValueError:
            pass
    return fallback


def extract_meeting_type(md_text: str, fallback: str = "Rollingwood Meeting") -> str:
    """Pull the meeting type from §2 Meeting Details, stripping trailing parentheticals."""
    m = _MEETING_TYPE_RE.search(md_text)
    if not m:
        return fallback
    return m.group(1).strip() or fallback


def export_to_pdf(
    md_text: str,
    pdf_path: Path,
    meeting_type: str,
    meeting_date: str,
) -> None:
    body_html = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "sane_lists"]
    )
    issue_title = (
        f"{meeting_type} — {meeting_date}" if meeting_date else meeting_type
    )
    doc = _HTML_TEMPLATE.format(
        issue_title=html.escape(issue_title),
        meeting_date=html.escape(meeting_date).replace("'", "\\'"),
        body=body_html,
    )
    HTML(string=doc).write_pdf(str(pdf_path), stylesheets=[CSS(string=_CSS)])
