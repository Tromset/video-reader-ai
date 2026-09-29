from __future__ import annotations

import re
from pathlib import Path

import pytest

from video_reader.models import Segment
from video_reader.transcript import load_segments

FIXTURES = Path(__file__).parent / "fixtures"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def joined(segments: list[Segment]) -> str:
    return norm(" ".join(s.text for s in segments))


def assert_well_formed(segments: list[Segment]) -> None:
    assert segments, "expected at least one segment"
    starts = [s.start for s in segments]
    assert starts == sorted(starts)
    for s in segments:
        assert isinstance(s, Segment)
        assert s.text.strip(), f"empty segment: {s}"
        assert s.end >= s.start
        assert "<" not in s.text and ">" not in s.text


def test_manual_vtt():
    segs = load_segments(FIXTURES / "manual.en.vtt")
    assert_well_formed(segs)
    text = joined(segs)
    # NOTE block is not transcript content
    assert "comment" not in text
    assert "note" not in text
    # HTML entities decoded
    assert "&amp;" not in text and "&quot;" not in text and "&#39;" not in text
    assert "tom & jerry are here." in text
    assert "rock & roll" in text
    assert "it's a \"great\" day." in text
    # voice tag removed
    assert "<v" not in text
    # first segment timing (may have been merged with following ones, start must hold)
    assert segs[0].start == pytest.approx(1.0, abs=0.01)
    assert segs[0].end >= 4.5 - 0.01
    assert segs[-1].start >= 5.0
    assert segs[-1].end == pytest.approx(12.0, abs=0.01)


def test_manual_vtt_timings_present():
    segs = load_segments(FIXTURES / "manual.en.vtt")
    starts = [round(s.start, 2) for s in segs]
    # The cue starting at 10 s must be reachable either as its own segment or merged
    assert starts[0] == 1.0
    assert any(s.start <= 10.0 <= s.end for s in segs) or 10.0 in starts


def test_srt():
    segs = load_segments(FIXTURES / "sample.srt")
    assert_well_formed(segs)
    text = joined(segs)
    assert "bonjour & bienvenue dans cette vidéo." in text
    assert "nous allons parler de tests automatisés." in text  # multi-line cue joined
    assert "merci d'avoir regardé." in text
    assert "<i>" not in text and "</i>" not in text
    assert "-->" not in text
    assert segs[0].start == pytest.approx(1.0, abs=0.01)
    assert segs[-1].end == pytest.approx(11.9, abs=0.01)
    assert segs[-1].start >= 5.0
    # 2nd cue timing preserved (own segment or inside merged one)
    assert any(s.start <= 5.0 and s.end >= 8.25 - 0.01 for s in segs) or any(
        abs(s.start - 5.0) < 0.01 for s in segs
    )


PHRASES = [
    "hello everyone welcome to the show",
    "today we talk about python testing",
    "it is really quite simple indeed",
    "thanks for watching and goodbye",
]


def test_youtube_auto_dedup():
    segs = load_segments(FIXTURES / "youtube_auto.en.vtt")
    assert_well_formed(segs)
    for s in segs:
        assert "<" not in s.text and ">" not in s.text
        assert "align:" not in s.text and "position:" not in s.text
        assert not re.search(r"\d\d:\d\d:\d\d", s.text)
    text = joined(segs)
    for phrase in PHRASES:
        assert text.count(phrase) == 1, f"{phrase!r} appears {text.count(phrase)}x in {text!r}"
    # total word count equals the source words exactly (no cascade repetition, nothing lost)
    assert text.split() == " ".join(PHRASES).split()


def test_youtube_auto_timing():
    segs = load_segments(FIXTURES / "youtube_auto.en.vtt")
    assert segs[0].start == pytest.approx(0.32, abs=0.5)
    assert segs[-1].end <= 12.1
    assert all(s.start >= 0 for s in segs)
    # ordered, and no segment starts before the previous one
    for a, b in zip(segs, segs[1:]):
        assert b.start >= a.start


def test_srt_unsorted_input_is_sorted(tmp_path):
    p = tmp_path / "x.srt"
    p.write_text(
        "1\n00:00:10,000 --> 00:00:12,000\nsecond block\n\n"
        "2\n00:00:01,000 --> 00:00:03,000\nfirst block\n",
        encoding="utf-8",
    )
    segs = load_segments(p)
    starts = [s.start for s in segs]
    assert starts == sorted(starts)
    assert joined(segs) == "first block second block"
