from __future__ import annotations

import json
import shutil
from pathlib import Path

from video_reader.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_cli_local_video_with_srt(sample_video, tmp_path, capsys):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    video = src_dir / sample_video.name
    shutil.copy(sample_video, video)
    shutil.copy(FIXTURES / "sample.srt", video.with_suffix(".srt"))
    out = tmp_path / "out"

    code = main([str(video), "--out", str(out), "--max-frames", "6", "--interval", "4"])
    captured = capsys.readouterr()
    assert code == 0

    lines = [l for l in captured.out.splitlines() if l.strip()]
    assert len(lines) == 1, f"stdout must contain only the digest path, got {captured.out!r}"
    digest = Path(lines[0])
    assert digest.is_absolute()
    assert digest.exists() and digest.name == "digest.md"

    md = digest.read_text(encoding="utf-8")
    assert "tests automatisés" in md
    assert "bienvenue" in md
    assert "frames/" in md and ".jpg" in md
    frames = list((digest.parent / "frames").glob("*.jpg"))
    assert 1 <= len(frames) <= 6
    assert (digest.parent / "transcript.json").exists()
    json.loads((digest.parent / "meta.json").read_text(encoding="utf-8"))

    # the user's files must never be removed
    assert video.exists() and video.stat().st_size > 0
    assert video.with_suffix(".srt").exists()


def test_cli_no_frames(sample_video, tmp_path, capsys):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    video = src_dir / sample_video.name
    shutil.copy(sample_video, video)
    shutil.copy(FIXTURES / "sample.srt", video.with_suffix(".srt"))
    out = tmp_path / "out"

    code = main([str(video), "--out", str(out), "--no-frames"])
    captured = capsys.readouterr()
    assert code == 0
    digest = Path(captured.out.strip().splitlines()[-1])
    assert digest.exists()
    assert "![frame" not in digest.read_text(encoding="utf-8")
    assert video.exists()


def test_cli_nonexistent_source(tmp_path, capsys, monkeypatch):
    import socket

    def _no_network(*a, **k):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(socket, "getaddrinfo", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _no_network)

    # A missing local path may be treated as a URL by the CLI; either way it must fail.
    # Use a name that yt-dlp rejects without any network access (no scheme, no domain).
    code = main(["not-a-real-file.mp4", "--out", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code != 0
    assert captured.out.strip() == ""  # nothing on stdout on failure
