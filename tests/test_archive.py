"""Offline tests: a fake YouTube stands in for yt-dlp's network calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive  # noqa: E402
from transcripts import parse_json3, parse_vtt, to_paragraphs  # noqa: E402

JSON3 = json.dumps({"events": [
    {"tStartMs": 0, "segs": [{"utf8": "Hey everybody"}, {"utf8": " welcome back"}]},
    {"tStartMs": 1500, "segs": [{"utf8": "\n"}]},
    {"tStartMs": 31000, "segs": [{"utf8": "XRP is moving today"}]},
]})

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
<c>hello</c> there

00:00:03.000 --> 00:00:05.000
hello there
ripple news

01:00:02.500 --> 01:00:04.000
late line
"""


def test_parse_json3_and_paragraphs():
    cues = parse_json3(JSON3)
    assert cues == [(0.0, "Hey everybody welcome back"), (31.0, "XRP is moving today")]
    assert to_paragraphs(cues) == [(0.0, "Hey everybody welcome back"), (31.0, "XRP is moving today")]


def test_parse_vtt_dedupes_rolling_lines():
    assert parse_vtt(VTT) == [(1.0, "hello there"), (3.0, "ripple news"), (3602.5, "late line")]


def test_xrp_matching():
    assert archive.xrp_matches("XRPL and xrp and Ripple") == ["XRPL", "xrp", "Ripple"]
    assert archive.xrp_matches("a ripple effect in stocks") == []
    assert archive.xrp_matches("Garlinghouse on RLUSD") == ["RLUSD", "Garlinghouse"]


VIDEOS = {
    # id: (upload_date, title, description, has_captions)
    "new1": ("20261021", "XRP news today", "", True),
    "new2": ("20260601", "Bitcoin only", "nothing here", True),          # transcript mentions XRP
    "new3": ("20250102", "Stock market chat", "", True),                  # truly not XRP
    "new4": ("20241021", "Ripple update", "", False),                     # no captions
    "mem1": ("20250505", "Members stream", "", True),
    **{f"old{i}": ("20240901", "Old XRP video", "", True) for i in range(15)},
}


class FakeYDL:
    def __init__(self, opts):
        self.opts = opts

    def extract_info(self, url, download=False, process=True):
        if url.endswith("/videos"):
            return {"_type": "playlist", "entries": iter([{"id": k} for k in VIDEOS])}
        if url.endswith("/streams"):
            raise archive.yt_dlp.utils.DownloadError("This channel does not have a streams tab")
        vid = url.split("v=")[1]
        if vid == "mem1":
            raise archive.yt_dlp.utils.DownloadError("Join this channel to get access to members-only content")
        date, title, desc, caps = VIDEOS[vid]
        transcript = "XRP mentioned" if vid == "new2" else "general talk"
        return {
            "id": vid, "title": title, "description": desc, "upload_date": date,
            "duration": 600, "availability": "public", "live_status": "not_live",
            "automatic_captions": {"en": [{"ext": "json3", "url": f"cap://{transcript}"}]} if caps else {},
        }

    def urlopen(self, url):
        text = url.split("://")[1]
        body = json.dumps({"events": [{"tStartMs": 5000, "segs": [{"utf8": text}]}]}).encode()

        class R:
            def read(self):
                return body
        return R()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "ARCHIVE", tmp_path / "archive")
    monkeypatch.setattr(archive, "UPLOAD", tmp_path / "upload")
    monkeypatch.setattr(archive, "CATALOG", tmp_path / "data" / "catalog.json")
    monkeypatch.setattr(archive.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(archive.time, "sleep", lambda s: None)
    return tmp_path


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["archive.py", *argv])
    archive.main()


def test_end_to_end(sandbox, monkeypatch):
    run(monkeypatch, "--sleep", "0")
    cat = json.loads((sandbox / "data" / "catalog.json").read_text())
    assert cat["new1"]["status"] == "archived"
    assert cat["new2"]["status"] == "archived" and cat["new2"]["relevance"] == "transcript only"
    assert cat["new3"]["status"] == "not_xrp"
    assert cat["new4"]["status"] == "archived_no_transcript"
    assert cat["mem1"]["status"] == "not_public"
    # stopped paging after STOP_AFTER_OLDER old videos
    assert sum(1 for k in cat if k.startswith("old")) == archive.STOP_AFTER_OLDER

    md = (sandbox / "archive" / cat["new1"]["file"]).read_text()
    assert "https://www.youtube.com/watch?v=new1" in md and "[0:05] general talk" in md

    bundles = sorted(p.name for p in (sandbox / "upload").glob("*.md"))
    assert bundles == ["00_INDEX_AND_GUIDE.md",
                       "digital-perspectives-brad-kimes_2024-Q4.md",
                       "digital-perspectives-brad-kimes_2026-Q2.md",
                       "digital-perspectives-brad-kimes_2026-Q4.md"]
    index = (sandbox / "archive" / "INDEX.md").read_text()
    assert "Archived videos: **3**" in index and "members-only" in index

    # Second run: finished videos are not fetched again; the no-transcript one is retried.
    fetched = []
    orig = FakeYDL.extract_info

    def spy(self, url, download=False, process=True):
        fetched.append(url)
        return orig(self, url, download, process)
    monkeypatch.setattr(FakeYDL, "extract_info", spy)
    run(monkeypatch, "--sleep", "0")
    watched = [u.split("v=")[1] for u in fetched if "v=" in u]
    assert watched == ["new4"]
