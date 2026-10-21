"""Turn YouTube caption files (json3 or WebVTT) into clean, timestamped text."""

import html
import json
import re


def fmt_ts(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


def parse_json3(raw):
    """Return [(start_seconds, text), ...] from a YouTube json3 caption file."""
    data = json.loads(raw)
    cues = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = "".join(s.get("utf8", "") for s in segs)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cues.append((ev.get("tStartMs", 0) / 1000.0, text))
    return cues


_VTT_TIME = re.compile(r"(?:(\d+):)?(\d{2}):(\d{2})\.(\d{3})\s+-->")


def parse_vtt(raw):
    """Return [(start_seconds, text), ...] from WebVTT, removing the rolling
    duplicate lines that YouTube auto-captions contain."""
    cues = []
    last_line = None
    for block in re.split(r"\n\s*\n", raw.replace("\r", "")):
        lines = block.strip().split("\n")
        t_idx = next((i for i, l in enumerate(lines) if _VTT_TIME.search(l)), None)
        if t_idx is None:
            continue
        h, m, s, ms = _VTT_TIME.search(lines[t_idx]).groups()
        start = int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
        for line in lines[t_idx + 1:]:
            line = html.unescape(re.sub(r"<[^>]+>", "", line)).strip()
            if line and line != last_line:
                cues.append((start, line))
                last_line = line
    return cues


def to_paragraphs(cues, every=30):
    """Group cues into paragraphs of roughly `every` seconds, each starting
    with its timestamp so passages can be cited."""
    paras, cur, cur_start = [], [], None
    for start, text in cues:
        if cur_start is None:
            cur_start = start
        elif start - cur_start >= every:
            paras.append((cur_start, " ".join(cur)))
            cur, cur_start = [], start
        cur.append(text)
    if cur:
        paras.append((cur_start, " ".join(cur)))
    return paras
