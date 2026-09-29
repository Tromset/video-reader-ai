"""Shared fixtures. No test in this suite touches the network."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"ffmpeg unavailable: {exc}")
    if not exe or not Path(exe).exists():
        pytest.skip("ffmpeg binary not found")
    return exe


@pytest.fixture(scope="session")
def sample_video(ffmpeg_exe, tmp_path_factory) -> Path:
    """12 s, 320x240, 10 fps video: 3 x 4 s with sharp scene changes, + sine audio."""
    out = tmp_path_factory.mktemp("video") / "sample.mp4"
    cmd = [
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10:duration=4",
        "-f", "lavfi", "-i", "color=c=red:size=320x240:rate=10:duration=4",
        "-f", "lavfi", "-i", "smptebars=size=320x240:rate=10:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=12",
        "-filter_complex",
        "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]",
        "-map", "[v]", "-map", "3:a",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
        str(out),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"cannot run ffmpeg: {exc}")
    if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        pytest.skip(f"cannot generate sample video: {proc.stderr[-500:]}")
    return out
