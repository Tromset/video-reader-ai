from __future__ import annotations

import re

from video_reader.ffmpeg import probe_duration
from video_reader.frames import extract_frames

NAME_RE = re.compile(r"^\d{4}_\d{2}-\d{2}-\d{2}\.jpg$")


def _check(frames, out_dir, limit):
    assert len(frames) <= limit
    for f in frames:
        assert f.path.exists() and f.path.stat().st_size > 0
        with open(f.path, "rb") as fh:
            assert fh.read(3) == b"\xff\xd8\xff"  # JPEG magic
        assert NAME_RE.match(f.path.name), f.path.name
        assert f.path.parent.resolve() == out_dir.resolve()
        assert 0 <= f.time <= 13
    times = [f.time for f in frames]
    assert times == sorted(times)
    names = [f.path.name for f in frames]
    assert names == sorted(names)
    for a, b in zip(times, times[1:]):
        assert b - a >= 1.5  # contract: ~2 s minimum gap


def test_extract_frames_basic(sample_video, tmp_path):
    out = tmp_path / "frames"
    frames = extract_frames(sample_video, out, max_frames=10, interval=5)
    assert len(frames) >= 2
    _check(frames, out, 10)


def test_extract_frames_respects_max(sample_video, tmp_path):
    out = tmp_path / "frames"
    frames = extract_frames(sample_video, out, max_frames=2, interval=5)
    assert 1 <= len(frames) <= 2
    _check(frames, out, 2)


def test_extract_frames_max_width(sample_video, tmp_path):
    out = tmp_path / "frames"
    frames = extract_frames(sample_video, out, max_frames=5, interval=5)
    assert frames
    # 320 px source must not be upscaled beyond the 768 px cap; verify SOF dimensions
    for f in frames:
        data = f.path.read_bytes()
        i = 2
        width = None
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                width = int.from_bytes(data[i + 7 : i + 9], "big")
                break
            i += 2 + int.from_bytes(data[i + 2 : i + 4], "big")
        assert width is not None and width <= 768


def test_probe_duration(sample_video):
    d = probe_duration(sample_video)
    assert d is not None
    assert abs(d - 12.0) <= 0.5
