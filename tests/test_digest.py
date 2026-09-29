from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from video_reader.digest import render
from video_reader.models import FetchResult, Frame, Segment

TS_05 = re.compile(r"\[0?0:05\]")


def make_meta(**kw) -> FetchResult:
    base = dict(
        id="abc123",
        title="My Test Video Title",
        uploader="Some Uploader",
        duration=125.0,
        url="https://example.com/watch?v=abc123",
        description="A description.",
        chapters=[],
    )
    base.update(kw)
    return FetchResult(**base)


def make_frames(out_dir: Path, times: list[float]) -> list[Frame]:
    fdir = out_dir / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, t in enumerate(times, 1):
        h, m, s = int(t // 3600), int(t % 3600 // 60), int(t % 60)
        p = fdir / f"{i:04d}_{h:02d}-{m:02d}-{s:02d}.jpg"
        p.write_bytes(b"")
        frames.append(Frame(time=t, path=p))
    return frames


SEGMENTS = [
    Segment(5.0, 9.0, "ALPHA_TEXT first spoken words"),
    Segment(20.0, 25.0, "BRAVO_TEXT second spoken words"),
    Segment(80.0, 90.0, "CHARLIE_TEXT much later words"),
]


def test_render_writes_files(tmp_path):
    frames = make_frames(tmp_path, [12.0, 85.0])
    digest = render(make_meta(), SEGMENTS, frames, tmp_path)
    digest = Path(digest)
    assert digest.exists() and digest.name == "digest.md"
    assert digest.parent.resolve() == tmp_path.resolve()
    assert (tmp_path / "transcript.json").exists()
    assert (tmp_path / "meta.json").exists()

    md = digest.read_text(encoding="utf-8")
    assert "My Test Video Title" in md
    assert TS_05.search(md), md
    for word in ("ALPHA_TEXT", "BRAVO_TEXT", "CHARLIE_TEXT"):
        assert word in md

    # frames referenced relatively
    refs = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md)
    assert len(refs) == 2
    for r in refs:
        assert r.startswith("frames/") and r.endswith(".jpg")
        assert not r.startswith("/") and str(tmp_path) not in r
        assert (tmp_path / r).exists()
    assert "![frame 00:12]" in md or "![frame 0:12]" in md
    assert "![frame 01:25]" in md or "![frame 1:25]" in md


def test_render_json_valid(tmp_path):
    frames = make_frames(tmp_path, [12.0])
    render(make_meta(), SEGMENTS, frames, tmp_path)
    tr = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert isinstance(tr, list) and len(tr) == 3
    assert "ALPHA_TEXT first spoken words" in json.dumps(tr)
    assert meta["title"] == "My Test Video Title"
    assert meta["id"] == "abc123"


def test_render_frame_placement(tmp_path):
    frames = make_frames(tmp_path, [12.0])
    md = Path(render(make_meta(), SEGMENTS, frames, tmp_path)).read_text(encoding="utf-8")
    ref = md.index("frames/0001_")
    # frame at 12 s: after text starting at 5 s, before text starting at 80 s
    assert md.index("ALPHA_TEXT") < ref < md.index("CHARLIE_TEXT")


def test_render_frame_before_first_text(tmp_path):
    frames = make_frames(tmp_path, [1.0])
    md = Path(render(make_meta(), SEGMENTS, frames, tmp_path)).read_text(encoding="utf-8")
    ref = md.index("frames/0001_")
    assert ref < md.index("CHARLIE_TEXT")


def test_render_no_segments(tmp_path):
    frames = make_frames(tmp_path, [10.0, 40.0])
    digest = Path(render(make_meta(), [], frames, tmp_path))
    md = digest.read_text(encoding="utf-8")
    assert "My Test Video Title" in md
    assert md.count("frames/0001_") == 1 and md.count("frames/0002_") == 1
    assert json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8")) == []
    json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert re.search(r"transcript|transcription|subtitle|sous-titre", md, re.I)


def test_render_no_segments_no_frames(tmp_path):
    digest = Path(render(make_meta(), [], [], tmp_path))
    assert digest.exists()
    assert "My Test Video Title" in digest.read_text(encoding="utf-8")


def test_render_with_chapters(tmp_path):
    chapters = [
        {"title": "Intro_CHAPTER", "start_time": 0.0, "end_time": 60.0},
        {"title": "Deep_Dive_CHAPTER", "start_time": 60.0, "end_time": 125.0},
    ]
    frames = make_frames(tmp_path, [12.0, 85.0])
    md = Path(render(make_meta(chapters=chapters), SEGMENTS, frames, tmp_path)).read_text(
        encoding="utf-8"
    )
    assert "Intro_CHAPTER" in md and "Deep_Dive_CHAPTER" in md
    assert md.index("Intro_CHAPTER") < md.index("Deep_Dive_CHAPTER")
    # chapter titles may also appear in a table of contents: use the last occurrence
    # (the heading in the body) to check they frame the text they cover
    intro, deep = md.rindex("Intro_CHAPTER"), md.rindex("Deep_Dive_CHAPTER")
    assert intro < md.index("ALPHA_TEXT") < md.index("BRAVO_TEXT") < deep
    assert deep < md.index("CHARLIE_TEXT")
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert len(meta["chapters"]) == 2


def test_render_creates_out_dir(tmp_path):
    out = tmp_path / "nested" / "out"
    digest = Path(render(make_meta(), SEGMENTS, [], out))
    assert digest.exists()
