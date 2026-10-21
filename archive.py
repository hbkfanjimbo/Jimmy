#!/usr/bin/env python3
"""XRP research archive builder.

Lists every upload on the channels in channels.txt, keeps the free, public,
XRP-related videos published inside the date window, saves each one's
metadata, description and transcript as a Markdown file, then builds an index
and ChatGPT-ready bundles. Safe to re-run: finished videos are skipped and
anything that failed is retried.
"""

import argparse
import csv
import datetime as dt
import json
import random
import re
import sys
import time
from pathlib import Path

import yt_dlp

from transcripts import fmt_ts, parse_json3, parse_vtt, to_paragraphs

ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "archive"
UPLOAD = ROOT / "chatgpt_upload"
CATALOG = ROOT / "data" / "catalog.json"
CHANNELS_FILE = ROOT / "channels.txt"

DEFAULT_SINCE = "2024-10-21"
DEFAULT_UNTIL = "2026-10-21"
# Uploads are listed newest first; once this many in a row are older than the
# window we stop paging (a few extra guard against pinned/out-of-order items).
STOP_AFTER_OLDER = 10
# Keep each ChatGPT bundle comfortably under ChatGPT's ~2M-token-per-file cap.
MAX_BUNDLE_CHARS = 4_000_000

# Statuses that are final; everything else is retried on the next run.
FINAL = {"archived", "not_xrp", "out_of_range", "not_public"}

XRP_PATTERNS = [
    (r"\bXRP\w*", re.I),          # XRP, XRPL, XRPHealthcare...
    (r"\bRipple\b", 0),           # capitalised only: avoids "ripple effect"
    (r"\bRLUSD\b", re.I),
    (r"\bGarlinghouse\b", re.I),
    (r"\bDavid Schwartz\b", re.I),
    (r"\bAlderoty\b", re.I),
    (r"\bMonica Long\b", re.I),
    (r"\bOn[- ]Demand Liquidity\b", re.I),
]
XRP_RE = [re.compile(p, f) for p, f in XRP_PATTERNS]


def log(msg):
    print(msg, flush=True)


def xrp_matches(text):
    found = []
    for rx in XRP_RE:
        for m in rx.findall(text or ""):
            if m.upper() not in (f.upper() for f in found):
                found.append(m)
    return found


def slugify(text, maxlen=60):
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return s[:maxlen].rstrip("-") or "video"


def ymd(d):
    """'20250314' -> '2025-03-14'"""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if d and len(d) == 8 else d


def quarter(date_iso):
    y, m = int(date_iso[:4]), int(date_iso[5:7])
    return f"{y}-Q{(m - 1) // 3 + 1}"


def read_channels():
    chans = []
    for line in CHANNELS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, url = (p.strip() for p in line.partition("|"))
        chans.append((name, url.rstrip("/")))
    return chans


def load_catalog():
    if CATALOG.exists():
        return json.loads(CATALOG.read_text())
    return {}


def save_catalog(cat):
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CATALOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(cat, indent=1, sort_keys=True))
    tmp.replace(CATALOG)


# --------------------------------------------------------------------- YouTube

def make_ydl(args, flat=False):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignore_no_formats_error": True,
        "noprogress": True,
    }
    if flat:
        opts.update({"extract_flat": "in_playlist", "lazy_playlist": True})
    if args.cookies_from_browser:
        opts["cookiesfrombrowser"] = (args.cookies_from_browser,)
    return yt_dlp.YoutubeDL(opts)


def iter_tab(ydl, url):
    """Yield flat entries of a channel tab, newest first, page by page."""
    res = ydl.extract_info(url, download=False, process=False)
    while res.get("_type") in ("url", "url_transparent"):
        res = ydl.extract_info(res["url"], download=False, process=False)
    for e in res.get("entries") or []:
        if e and e.get("id"):
            yield e


def classify_error(msg):
    m = msg.lower()
    if any(k in m for k in ("members-only", "members only", "join this channel", "private video",
                            "requires payment", "purchase", "sign in to confirm your age",
                            "video unavailable", "has been removed", "terminated")):
        return "not_public"
    if any(k in m for k in ("live event will begin", "premieres in", "is_upcoming",
                            "this live stream", "will begin in")):
        return "upcoming_or_live"
    return "error"


def fetch_url(ydl, url, tries=4):
    for i in range(tries):
        try:
            return ydl.urlopen(url).read().decode("utf-8", "replace")
        except Exception as exc:  # 429s on caption URLs are common: back off
            if i == tries - 1:
                raise
            wait = 10 * (2 ** i) + random.random() * 5
            log(f"      caption fetch failed ({exc}); retrying in {wait:.0f}s")
            time.sleep(wait)


def pick_track(info):
    """Prefer creator-uploaded English captions, else YouTube's auto captions."""
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    choices = [(k, manual[k], "creator captions") for k in manual
               if k.lower().startswith("en") and k != "live_chat"]
    choices += [(k, auto[k], "YouTube auto-generated captions")
                for k in ("en-orig", "en", "en-US") if k in auto]
    for lang, formats, source in choices:
        by_ext = {f.get("ext"): f for f in formats if f.get("url")}
        for ext in ("json3", "vtt"):
            if ext in by_ext:
                return by_ext[ext]["url"], ext, f"{source} ({lang})"
    return None


def get_transcript(ydl, info):
    track = pick_track(info)
    if not track:
        return None, "none available"
    url, ext, source = track
    raw = fetch_url(ydl, url)
    cues = parse_json3(raw) if ext == "json3" else parse_vtt(raw)
    if not cues:
        return None, f"empty ({source})"
    return cues, source


# -------------------------------------------------------------------- Writing

def write_video_md(path, info, channel_name, cues, transcript_source, matches):
    vid = info["id"]
    url = f"https://www.youtube.com/watch?v={vid}"
    date = ymd(info.get("upload_date"))
    dur = info.get("duration")
    lines = [
        f"# {info.get('title', '').strip()}",
        "",
        f"- **Video ID:** {vid}",
        f"- **Channel:** {channel_name}",
        f"- **Published:** {date}",
        f"- **URL:** {url}",
        f"- **Duration:** {fmt_ts(dur) if dur else 'unknown'}",
        f"- **Type:** {'livestream' if info.get('was_live') or info.get('live_status') == 'was_live' else 'video'}",
        f"- **Views at capture:** {info.get('view_count', 'unknown')}",
        f"- **Captured:** {dt.date.today().isoformat()}",
        f"- **Transcript source:** {transcript_source}",
        f"- **XRP terms found:** {', '.join(matches) if matches else 'none'}",
        "",
        "> Auto-generated captions can mis-hear names and numbers. Check the video at the",
        f"> timestamp before relying on an exact quote: {url}&t=SECONDS",
        "",
    ]
    if info.get("chapters"):
        lines += ["## Chapters", ""]
        lines += [f"- [{fmt_ts(c['start_time'])}] {c.get('title', '')}" for c in info["chapters"]]
        lines.append("")
    lines += ["## Description", "", (info.get("description") or "(none)").strip(), ""]
    lines += ["## Transcript", ""]
    if cues:
        for start, text in to_paragraphs(cues):
            lines += [f"[{fmt_ts(start)}] {text}", ""]
    else:
        lines += ["(No transcript was available when this was captured. The archiver will retry.)", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


# ----------------------------------------------------------------- Processing

def process_video(args, ydl, vid, channel_name, cat):
    rec = cat.get(vid, {})
    rec.update({"id": vid, "channel": channel_name, "checked": dt.date.today().isoformat()})
    cat[vid] = rec
    try:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    except Exception as exc:
        rec["status"], rec["reason"] = classify_error(str(exc)), str(exc)[:300]
        rec["tries"] = rec.get("tries", 0) + 1
        return rec

    rec["title"] = info.get("title", "")
    rec["date"] = ymd(info.get("upload_date") or info.get("release_date") or "")
    rec["duration"] = info.get("duration")

    if info.get("live_status") in ("is_upcoming", "is_live"):
        rec["status"], rec["reason"] = "upcoming_or_live", info["live_status"]
        return rec
    if info.get("availability") not in (None, "public", "unlisted"):
        rec["status"], rec["reason"] = "not_public", info.get("availability")
        return rec
    if not rec["date"] or not (args.since <= rec["date"] <= args.until):
        rec["status"], rec["reason"] = "out_of_range", ""
        return rec

    try:
        cues, source = get_transcript(ydl, info)
    except Exception as exc:
        cues, source = None, f"failed: {exc}"[:200]

    meta_text = " ".join([info.get("title") or "", info.get("description") or "",
                          " ".join(info.get("tags") or [])])
    matches = xrp_matches(meta_text)
    transcript_text = " ".join(t for _, t in cues) if cues else ""
    t_matches = xrp_matches(transcript_text)
    all_matches = matches + [m for m in t_matches if m.upper() not in (x.upper() for x in matches)]

    if not all_matches:
        if cues:
            rec["status"], rec["reason"] = "not_xrp", "no XRP terms in title, description, tags or transcript"
        else:
            rec["status"], rec["reason"] = "unclassified_no_transcript", source
        return rec

    rec["relevance"] = "title/description/tags" if matches else "transcript only"
    rec["matches"] = all_matches
    year = rec["date"][:4]
    rel = Path(slugify(channel_name)) / year / f"{rec['date']}_{vid}_{slugify(rec['title'])}.md"
    old = rec.get("file")
    if old and old != str(rel) and (ARCHIVE / old).exists():
        (ARCHIVE / old).unlink()
    write_video_md(ARCHIVE / rel, info, channel_name, cues, source, all_matches)
    rec["file"] = str(rel)
    rec["transcript"] = source if cues else None
    if cues:
        rec["status"], rec["reason"] = "archived", ""
    else:
        rec["status"], rec["reason"] = "archived_no_transcript", source
    return rec


def needs_work(rec, args):
    if not rec or "status" not in rec:
        return True
    if rec["status"] in FINAL:
        return False
    if rec["status"] == "error" and rec.get("tries", 0) >= args.max_tries:
        return False
    return True


def crawl_channel(args, name, url, cat):
    tabs = ["videos", "streams"] + (["shorts"] if args.include_shorts else [])
    done = 0
    for tab in tabs:
        log(f"\n== {name}: /{tab} ==")
        lister, ydl = make_ydl(args, flat=True), make_ydl(args)
        older_in_row = 0
        try:
            entries = iter_tab(lister, f"{url}/{tab}")
            for i, e in enumerate(entries, 1):
                vid = e["id"]
                rec = cat.get(vid)
                if rec and rec.get("date") and rec["date"] < args.since:
                    older_in_row += 1
                    if older_in_row >= STOP_AFTER_OLDER:
                        log(f"   reached videos older than {args.since}; done with this tab")
                        break
                    continue
                if not needs_work(rec, args):
                    older_in_row = 0
                    continue
                if args.limit and done >= args.limit:
                    log(f"   --limit {args.limit} reached")
                    return done
                rec = process_video(args, ydl, vid, name, cat)
                done += 1
                save_catalog(cat)
                log(f"   [{i}] {rec.get('date', '?')}  {rec['status']:<26} {rec.get('title', vid)[:70]}")
                if rec.get("date") and rec["date"] < args.since:
                    older_in_row += 1
                    if older_in_row >= STOP_AFTER_OLDER:
                        log(f"   reached videos older than {args.since}; done with this tab")
                        break
                else:
                    older_in_row = 0
                time.sleep(args.sleep + random.random() * args.sleep)
        except yt_dlp.utils.DownloadError as exc:
            if "does not have a" in str(exc).lower() and "tab" in str(exc).lower():
                log(f"   (channel has no /{tab} tab)")
            else:
                log(f"   could not list /{tab}: {exc}")
    return done


# ------------------------------------------------------------------- Outputs

def in_window(rec, args):
    return rec.get("date") and args.since <= rec["date"] <= args.until


def build_outputs(args, cat):
    kept = sorted((r for r in cat.values()
                   if r.get("status") in ("archived", "archived_no_transcript")
                   and in_window(r, args) and r.get("file") and (ARCHIVE / r["file"]).exists()),
                  key=lambda r: (r["date"], r["id"]))
    excluded = sorted((r for r in cat.values()
                       if r.get("status") not in ("archived", "archived_no_transcript", "out_of_range")
                       and (not r.get("date") or in_window(r, args))),
                      key=lambda r: (r.get("date") or "", r["id"]))
    ARCHIVE.mkdir(exist_ok=True)

    with open(ARCHIVE / "index.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "channel", "title", "video_id", "url", "duration_sec",
                    "transcript", "relevance", "xrp_terms", "file"])
        for r in kept:
            w.writerow([r["date"], r["channel"], r["title"], r["id"],
                        f"https://www.youtube.com/watch?v={r['id']}", r.get("duration") or "",
                        r.get("transcript") or "MISSING", r.get("relevance", ""),
                        "; ".join(r.get("matches", [])), r["file"]])

    idx = [f"# XRP Research Archive — Index",
           "",
           f"Window: {args.since} to {args.until} (inclusive). Last built: {dt.datetime.now():%Y-%m-%d %H:%M}.",
           f"Archived videos: **{len(kept)}** "
           f"({sum(1 for r in kept if r.get('transcript'))} with transcripts).",
           "",
           "| Date | Channel | Title | Video | Transcript |",
           "|---|---|---|---|---|"]
    for r in kept:
        title = r["title"].replace("|", "/")
        idx.append(f"| {r['date']} | {r['channel']} | {title} | "
                   f"[{r['id']}](https://www.youtube.com/watch?v={r['id']}) | "
                   f"{'yes' if r.get('transcript') else 'MISSING'} |")
    idx += ["", "## Checked but not archived", "",
            "Videos seen inside the window (or with unknown date) that were left out, and why.", "",
            "| Date | Channel | Title / ID | Status | Reason |", "|---|---|---|---|---|"]
    for r in excluded:
        idx.append(f"| {r.get('date') or '?'} | {r['channel']} | "
                   f"{(r.get('title') or r['id']).replace('|', '/')} | {r['status']} | "
                   f"{(r.get('reason') or '').replace('|', '/')[:120]} |")
    (ARCHIVE / "INDEX.md").write_text("\n".join(idx) + "\n")

    # ChatGPT bundles: one file per channel per quarter (split if very large).
    UPLOAD.mkdir(exist_ok=True)
    for old in UPLOAD.glob("*.md"):
        old.unlink()
    groups = {}
    for r in kept:
        groups.setdefault((slugify(r["channel"]), quarter(r["date"])), []).append(r)
    bundle_names = []
    for (chan, q), recs in sorted(groups.items()):
        parts, cur, size = [], [], 0
        for r in recs:
            text = (ARCHIVE / r["file"]).read_text()
            if cur and size + len(text) > MAX_BUNDLE_CHARS:
                parts.append(cur)
                cur, size = [], 0
            cur.append(text)
            size += len(text)
        parts.append(cur)
        for n, part in enumerate(parts, 1):
            suffix = f"_part{n}" if len(parts) > 1 else ""
            name = f"{chan}_{q}{suffix}.md"
            header = (f"<!-- XRP research archive bundle: {chan}, {q}{suffix}. "
                      f"{len(part)} videos. Each video starts with a '# ' title line. -->\n\n")
            (UPLOAD / name).write_text(header + "\n\n---\n\n".join(part))
            bundle_names.append(name)

    guide = (ROOT / "CHATGPT_INSTRUCTIONS.md").read_text()
    (UPLOAD / "00_INDEX_AND_GUIDE.md").write_text(
        guide + "\n\n---\n\n## Files in this upload\n\n" +
        "\n".join(f"- {n}" for n in bundle_names) + "\n\n---\n\n" +
        (ARCHIVE / "INDEX.md").read_text())
    return kept, excluded


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default=DEFAULT_SINCE, help="first publish date, YYYY-MM-DD (inclusive)")
    ap.add_argument("--until", default=DEFAULT_UNTIL, help="last publish date, YYYY-MM-DD (inclusive)")
    ap.add_argument("--limit", type=int, default=0, help="process at most N videos (for a quick test)")
    ap.add_argument("--sleep", type=float, default=2.0, help="base pause between videos, seconds")
    ap.add_argument("--include-shorts", action="store_true", help="also check the Shorts tab")
    ap.add_argument("--cookies-from-browser", metavar="BROWSER",
                    help="e.g. chrome or safari, if YouTube asks you to sign in to confirm you're not a bot")
    ap.add_argument("--max-tries", type=int, default=3, help="give up on a failing video after N runs")
    ap.add_argument("--rebuild-only", action="store_true", help="skip YouTube; just rebuild index and bundles")
    args = ap.parse_args()

    cat = load_catalog()
    if not args.rebuild_only:
        for name, url in read_channels():
            crawl_channel(args, name, url, cat)
        save_catalog(cat)

    kept, excluded = build_outputs(args, cat)
    counts = {}
    for r in cat.values():
        if in_window(r, args) or not r.get("date"):
            counts[r.get("status", "?")] = counts.get(r.get("status", "?"), 0) + 1
    log("\n==================== SUMMARY ====================")
    log(f"Archived XRP videos in window: {len(kept)}")
    for k, v in sorted(counts.items()):
        log(f"   {k:<28} {v}")
    log(f"\nIndex:            {ARCHIVE / 'INDEX.md'}")
    log(f"Upload to ChatGPT: {UPLOAD}")
    if any(r.get("status") not in FINAL for r in excluded):
        log("\nSome videos were not finished (no transcript yet, live, or errors). Run again later to retry them.")


if __name__ == "__main__":
    sys.exit(main())
