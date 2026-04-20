# Rollingwood Report

Automated pipeline that watches the [City of Rollingwood YouTube channel](https://www.youtube.com/@cityofrollingwoodtexas), transcribes new council/commission meetings, and emails a structured briefing to Jeff. Runs daily in GitHub Actions.

## Architecture

```
Daily cron (GitHub Actions)
       ↓
  yt-dlp → check channel for new meeting videos
       ↓  (new video found + title matches meeting keywords)
  yt-dlp → download audio only (MP3, ~128kbps)
       ↓
  AssemblyAI → transcript with speaker diarization
       ↓
  Claude Opus 4.7 → structured summary (locked prompt in prompts/summary_prompt.md)
       ↓
  Google Drive upload + Gmail send
       ↓
  Commit updated processed_meetings.json
```

## One-time setup

### 1. Accounts & API keys

You need three things:

| Service | What to get | Cost |
|---|---|---|
| Anthropic | API key | ~$0.30/meeting |
| AssemblyAI | API key (sign up at assemblyai.com) | ~$0.24/meeting |
| Google Cloud | OAuth client credentials for Drive + Gmail | Free |

### 2. Generate Google OAuth token (one-time, local)

```bash
cd rollingwood-report
pip install -r requirements.txt
# Place client_secret.json from Google Cloud Console in this folder
python scripts/bootstrap_google_auth.py
```

A browser opens, you sign in as jeffm031@gmail.com, grant Drive + Gmail access. The script prints a JSON blob — copy it.

### 3. Push to GitHub and add secrets

```bash
git init
git add .
git commit -m "Initial Rollingwood Report"
gh repo create rollingwood-report --private --source=. --push
```

Then: **Settings → Secrets and variables → Actions → New repository secret**:

- `ANTHROPIC_API_KEY` — your Anthropic key
- `ASSEMBLYAI_API_KEY` — your AssemblyAI key
- `GOOGLE_CREDS_JSON` — the JSON blob from step 2

### 4. Test it

Go to the Actions tab → **Rollingwood Report** → **Run workflow**. It will pick up the most recent meeting it hasn't processed.

## Tuning

- **Prompt**: edit `prompts/summary_prompt.md`. Changes take effect on the next run.
- **What counts as a "meeting"**: edit `MEETING_TITLE_KEYWORDS` in `scripts/run.py`.
- **Schedule**: edit the cron in `.github/workflows/rollingwood.yml`. Default is daily at 8 AM CT.
- **Reprocess a meeting**: delete its entry from `processed_meetings.json` and push.

## Cost per meeting (estimate)

| Step | Cost |
|---|---|
| AssemblyAI transcription (~2 hours audio) | ~$0.24 |
| Claude Opus 4.7 summary (~40K input tokens, ~3K output) | ~$0.30 |
| GitHub Actions minutes (~5 min/run) | Free tier |
| **Total** | **~$0.54/meeting** |

Rollingwood holds maybe 15–20 meetings/year across all bodies → **<$15/year**.

## Troubleshooting

- **"Audio download failed"**: yt-dlp may need updating. It's pinned in requirements.txt; bump the version and push.
- **Transcript looks wrong**: AssemblyAI sometimes struggles with crowded rooms. Check the raw transcript in the Drive file.
- **Email not arriving**: check Gmail "Sent" folder — the workflow sends *as* you, so it shows in Sent.
- **Missed a meeting**: run the workflow manually. If the video is older than the 5 most recent, increase `max_videos` in `list_recent_videos()`.
