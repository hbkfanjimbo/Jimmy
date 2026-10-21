# XRP Research Archive

This tool builds a searchable local archive of free, public, XRP-related YouTube videos
published **October 21, 2024 – October 21, 2026** (both dates included), in a format
that ChatGPT can read and cite.

For every qualifying video it saves the title, channel, date, link, description,
chapters, and a **timestamped transcript**. It then builds:

- `archive/INDEX.md` and `archive/index.csv`: every archived video, plus a list of
  videos it checked but left out and the reason (members-only, not about XRP, and so on).
- `archive/<channel>/<year>/*.md`: one file per video.
- `chatgpt_upload/`: a few large files (one per channel per quarter) plus
  `00_INDEX_AND_GUIDE.md`. These are the files you upload to ChatGPT.

Channels are listed in `channels.txt`. The archive currently covers
**Digital Perspectives (Brad Kimes)**.

---

## How to run it on your Mac (about 10 minutes of your time, then it runs itself)

### 1. Download the tool
1. Go to <https://github.com/hbkfanjimbo/Jimmy> (sign in if asked).
2. Click the green **Code** button, then **Download ZIP**.
3. Open your **Downloads** folder and double-click the ZIP to unzip it. You'll get
   a folder called **Jimmy-main**.
4. Move that folder somewhere you'll keep it, for example your **Documents**
   folder. The rest of these steps assume it's in Documents.

### 2. Open Terminal
Press **⌘ Command + Space**, type **Terminal**, and press **Return**.

### 3. Run a quick test (3 videos)
Copy this line, paste it into Terminal, and press **Return**:

```
cd ~/Documents/Jimmy-main && bash start.sh --limit 3
```

- The first time, it installs what it needs. You won't need an admin password, and
  everything stays inside your home folder.
- If a box pops up asking to install **command line developer tools**, click
  **Install**, wait for it to finish, then paste the line again.
- When it finishes, a Finder window opens showing `chatgpt_upload`.

### 4. Build the full archive
```
cd ~/Documents/Jimmy-main && bash start.sh
```
Two years of daily videos can take **1–3 hours**. The Mac stays awake while it runs.
You can close Terminal at any point: the next run picks up where it stopped. Run the
same command later to add new videos and retry any that failed.

### 5. Set up ChatGPT
1. In ChatGPT, click **Projects → New project** and name it something like
   *XRP Research*.
2. Open the project's **Instructions** and paste in everything from
   `CHATGPT_INSTRUCTIONS.md`.
3. Under **Files**, upload everything in the `chatgpt_upload` folder, starting with
   `00_INDEX_AND_GUIDE.md`.
4. Start chats inside that project. ChatGPT will quote the videos and give
   timestamped links you can click to check them.

After each update run, delete the old files from the ChatGPT project and upload the
new `chatgpt_upload` files.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `Sign in to confirm you're not a bot` | Open YouTube in Chrome and make sure you're signed in, then run `bash start.sh --cookies-from-browser chrome` |
| `HTTP Error 429` / many errors | YouTube is limiting requests. Wait an hour and run again, or slow down with `bash start.sh --sleep 6` |
| `command not found: uv` after install | Close Terminal, open it again, and re-run the command |
| Anything else | Copy the last ~20 lines from Terminal and paste them to Claude or ChatGPT |

## Options
```
bash start.sh --help              all options
bash start.sh --include-shorts    also check YouTube Shorts (off by default)
bash start.sh --rebuild-only      rebuild index and ChatGPT files without going online
```

## Adding channels
Add a line to `channels.txt`, for example
`Some Channel | https://www.youtube.com/@SomeHandle`, then run `bash start.sh`.

## How videos are chosen
- **Date:** YouTube's publish date (or the stream date for livestreams) falls within
  the window.
- **Free and public:** members-only, private, paid, and age-restricted videos are
  skipped and listed in INDEX.md. Upcoming and in-progress livestreams are retried on
  the next run.
- **XRP-related:** at least one of these terms appears in the title, description,
  tags, or transcript: XRP or XRPL, *Ripple* (capitalized), RLUSD, Garlinghouse,
  David Schwartz, Alderoty, Monica Long, On-Demand Liquidity. Each video file records
  which terms matched and whether the match came only from the transcript.
- **Transcripts:** captions uploaded by the creator are used when available;
  otherwise YouTube's auto-captions are used. Videos without captions are still
  archived with their metadata, marked `MISSING`, and retried on later runs.

The archive stays on your Mac. It isn't uploaded to GitHub.
