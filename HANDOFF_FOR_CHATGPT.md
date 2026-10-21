# Handoff: Claude → ChatGPT (XRP research archive)

Claude keeps this file updated with project status. Read this first.

## Status
- DONE: Archive builder written and tested offline (simulated YouTube, 4/4 tests pass).
- NOT YET RUN on real YouTube. Claude's cloud machine can't reach YouTube; the user runs it on their Mac.
- Channels so far: Digital Perspectives (Brad Kimes), handle @DigitalPerspectives (not yet confirmed).
- Window: 2024-10-21 to 2026-10-21, inclusive.

## How it works (repo: github.com/hbkfanjimbo/Jimmy)
- `bash start.sh` installs Python (via uv), yt-dlp and deno, then runs `archive.py`.
- Keeps only free, public videos that mention XRP terms (XRP/XRPL, Ripple, RLUSD, Garlinghouse,
  David Schwartz, Alderoty, Monica Long, On-Demand Liquidity) in the title, description, tags or transcript.
- Output: `archive/INDEX.md` (included and excluded videos, with reasons), one .md file per video
  (metadata + timestamped transcript), and `chatgpt_upload/` (one bundle per quarter + `00_INDEX_AND_GUIDE.md`).
- Resumable: re-running adds new videos and retries failed ones.
- Citation rules for ChatGPT: CHATGPT_INSTRUCTIONS.md.

## Conventions both assistants follow
1. Cite as: title, date, `https://www.youtube.com/watch?v=ID&t=SECONDS`.
2. Label every statement as creator claim, verified fact (name the source), or speculation.
3. Transcripts are mostly auto-captions; flag exact numbers and quotes for checking against the video.
4. Never guess what a video said; say when the archive doesn't cover something.
5. Not financial advice.
6. Keep replies to the user short, with copy-paste-ready steps.

## Open questions for the user
- Are there more channels? The original list stopped after #1.
- Confirm the test run (`bash start.sh --limit 3`) shows Brad Kimes videos.
