from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from video_reader.cli import main
from video_reader.models import FetchResult
from video_reader.navigation import select
from video_reader.timestamps import format_timestamp, parse_timestamp


@pytest.mark.parametrize(("value", "expected"), [
    ("0", 0), ("83.5", 83.5), ("01:23.500", 83.5),
    ("01:02:03.250", 3723.25), ("123:45", 7425),
])
def test_timestamps(value, expected):
    assert parse_timestamp(value) == expected
    assert parse_timestamp(format_timestamp(expected)) == expected


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "1e2", "1:60", "1:2", "1:60:00",
                                       "1:00:60", "1.1234", "", "00:00:00:01"])
def test_invalid_timestamps(value):
    with pytest.raises(ValueError):
        parse_timestamp(value)


@pytest.mark.parametrize("options", [
    ["--at", "1", "--start", "0", "--end", "2"],
    ["--start", "0"], ["--end", "1"], ["--start", "2", "--end", "1"],
    ["--at", "nan"], ["--at", "-1"], ["--interval", "0"], ["--interval", "inf"],
    ["--interval", "0.0001"], ["--max-frames", "0"], ["--scene-threshold", "nan"],
    ["--context", "-1"], ["--block", "0"], ["--no-frames", "--keep-video"],
])
def test_reject_bad_options_before_fetch(options, monkeypatch):
    monkeypatch.setattr("video_reader.cli.fetch", lambda *a, **kw: pytest.fail("must not fetch"))
    with pytest.raises(SystemExit) as exc:
        main(["missing.mp4", *options])
    assert exc.value.code == 2


def _result(capsys) -> Path:
    output = capsys.readouterr()
    lines = output.out.strip().splitlines()
    assert len(lines) == 1, output
    path = Path(lines[0])
    assert path.is_absolute() and path.is_file()
    return path


def _prepare(sample_video, tmp_path, capsys) -> tuple[Path, Path]:
    video = tmp_path / "local clip.mp4"
    shutil.copy(sample_video, video)
    video.with_suffix(".srt").write_text(
        "1\n00:00:00,000 --> 00:00:03,000\nBEFORE.\n\n"
        "2\n00:00:04,000 --> 00:00:07,000\nRED SCENE.\n\n"
        "3\n00:00:09,000 --> 00:00:11,000\nAFTER\n", encoding="utf-8",
    )
    assert main([str(video), "--out", str(tmp_path / "out"), "--max-frames", "2"]) == 0
    return _result(capsys), video


def _pixel(ffmpeg_exe, path) -> tuple[int, int, int]:
    proc = subprocess.run(
        [ffmpeg_exe, "-v", "error", "-i", str(path), "-vf", "scale=1:1",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    )
    assert len(proc.stdout) == 3
    return tuple(proc.stdout)


def test_revisit_seeks_backward_and_preserves_originals(sample_video, ffmpeg_exe, tmp_path, capsys, monkeypatch):
    digest, video = _prepare(sample_video, tmp_path, capsys)
    original = {p: p.read_bytes() for p in digest.parent.rglob("*") if p.is_file()}
    video_bytes = video.read_bytes()
    monkeypatch.setattr("video_reader.cli.fetch", lambda *a, **kw: pytest.fail("reuse local video"))
    monkeypatch.setattr("video_reader.frames._scene_times", lambda *a, **kw: pytest.fail("no scene scan"))
    assert main([str(digest), "--at", "9.2", "4.1", "--at", "4.2", "--context", "0"]) == 0
    report = _result(capsys)
    data = json.loads(report.with_suffix(".json").read_text())
    assert data["requested_timestamps"] == [9.2, 4.1, 4.2]
    assert len(data["frames"]) == 3
    assert data["transcript_source"] == "sous-titres"
    assert "BEFORE" not in report.read_text()
    assert "RED SCENE." in report.read_text()
    assert "AFTER" in report.read_text()
    images = [report.parent / f["path"] for f in data["frames"]]
    for path in images[1:]:
        red, green, blue = _pixel(ffmpeg_exe, path)
        assert red > 200 and green < 40 and blue < 40
    assert _pixel(ffmpeg_exe, images[0])[1] > 40  # bars at 9.2 s, not the red scene
    assert "04.100" in report.read_text() and "04.200" in report.read_text()
    assert "04-100" in images[1].name and "04-200" in images[2].name
    assert all(p.read_bytes() == content for p, content in original.items())
    assert video.read_bytes() == video_bytes

    assert main([str(digest.parent), "--start", "3", "--end", "9", "--interval", "2"]) == 0
    second = _result(capsys)
    assert second != report and report.is_file()
    range_data = json.loads(second.with_suffix(".json").read_text())
    assert range_data["requested_timestamps"] == [3, 5, 7]
    assert [s["text"] for s in range_data["segments"]] == ["RED SCENE."]
    assert all(p.read_bytes() == content for p, content in original.items())


def test_transcript_navigation_without_video(sample_video, tmp_path, capsys, monkeypatch):
    digest, video = _prepare(sample_video, tmp_path, capsys)
    video.unlink()
    monkeypatch.setattr("video_reader.cli.fetch", lambda *a, **kw: pytest.fail("transcript is cached"))
    assert main([str(digest), "--at", "7.5", "--context", "1", "--no-frames"]) == 0
    report = _result(capsys)
    data = json.loads(report.with_suffix(".json").read_text())
    assert data["frames"] == []
    # The cue starts before the window [6.5, 8.5], but overlaps it.
    assert data["segments"] == [{"start": 4.0, "end": 7.0, "text": "RED SCENE."}]
    assert data["transcript_windows"] == [{"start": 6.5, "end": 8.5}]
    assert not (report.parent / "frames").exists()


@pytest.mark.parametrize("options", [["--at", "12"], ["--at", "15"],
                                      ["--start", "0", "--end", "13"],
                                      ["--at", "1", "2", "--max-frames", "1"]])
def test_out_of_range_is_explicit(sample_video, tmp_path, capsys, options):
    digest, _ = _prepare(sample_video, tmp_path, capsys)
    assert main([str(digest), *options]) == 1
    result = capsys.readouterr()
    assert result.out == "" and "error:" in result.err
    assert not (digest.parent / "inspections").exists()


def test_capped_range_spans_video_without_materializing_all_times():
    result = select(None, 0, 36000, 5, .001, 3, 36000)
    assert result.capped
    assert len(result.times) == 3
    assert result.times[0] == 0
    assert result.times[-1] == 35999.999
    assert result.windows == [(0, 36000)]


def test_url_cache_and_redownload(sample_video, tmp_path, capsys, monkeypatch):
    calls = []

    def fake_fetch(source, workdir, langs, need_video, **kw):
        calls.append(source)
        path = workdir / "video.mp4"
        shutil.copy(sample_video, path)
        return FetchResult(id="remote", title="Remote", uploader=None, duration=12,
                           url=source, description=None, video_path=path)

    monkeypatch.setattr("video_reader.cli.fetch", fake_fetch)
    # Initial preparation without caching keeps the original cleanup contract.
    assert main(["https://example.com/video", "--out", str(tmp_path / "out"), "--max-frames", "1"]) == 0
    digest = _result(capsys)
    assert not (digest.parent / "media").exists()
    assert not list((tmp_path / "out").glob(".work-*"))
    digest_bytes = digest.read_bytes()
    # A follow-up can populate the cache; the next follow-up reuses it.
    assert main([str(digest), "--at", "5", "--keep-video"]) == 0
    _result(capsys)
    assert len(calls) == 2
    info = json.loads((digest.parent / "meta.json").read_text())
    assert info["source"] == "https://example.com/video"
    assert info["video_path"] == "media/video.mp4"
    assert (digest.parent / info["video_path"]).read_bytes() == sample_video.read_bytes()
    monkeypatch.setattr("video_reader.cli.fetch", lambda *a, **kw: pytest.fail("use cache"))
    assert main([str(digest.parent), "--at", "1"]) == 0
    _result(capsys)
    assert digest.read_bytes() == digest_bytes
    assert not list(digest.parent.glob(".work-*"))


def test_direct_seek_caches_remote(sample_video, tmp_path, capsys, monkeypatch):
    def fake_fetch(source, workdir, langs, **kw):
        video = workdir / "video.mp4"
        shutil.copy(sample_video, video)
        return FetchResult(id="cached", title="Cached", uploader=None, duration=12,
                           url=source, description=None, video_path=video)

    monkeypatch.setattr("video_reader.cli.fetch", fake_fetch)
    monkeypatch.setattr("video_reader.frames._scene_times", lambda *a, **kw: pytest.fail("no scene scan"))
    assert main(["https://example.com/cached", "--at", "00:05.100", "--keep-video",
                 "--out", str(tmp_path / "out")]) == 0
    report = _result(capsys)
    directory = report.parent.parent.parent
    assert (directory / "digest.md").is_file()
    assert (directory / "media/video.mp4").is_file()
    assert "Aucune transcription" in report.read_text()
    assert not list((tmp_path / "out").glob(".work-*"))
    monkeypatch.setattr("video_reader.cli.fetch", lambda *a, **kw: pytest.fail("use cache"))
    assert main([str(directory), "--at", "5.2"]) == 0
    _result(capsys)


def test_failed_decode_leaves_no_misleading_report(sample_video, tmp_path, capsys):
    digest, video = _prepare(sample_video, tmp_path, capsys)
    video.write_bytes(b"invalid video")
    assert main([str(digest), "--at", "5"]) == 1
    result = capsys.readouterr()
    assert result.out == "" and "Aucune image décodable" in result.err
    assert list((digest.parent / "inspections").iterdir()) == []
    assert not list(digest.parent.glob(".work-*"))


def test_invalid_or_old_local_digest(tmp_path, capsys):
    directory = tmp_path / "broken"
    directory.mkdir()
    assert main([str(directory), "--at", "1"]) == 1
    assert "Digest illisible" in capsys.readouterr().err
    (directory / "meta.json").write_text(json.dumps({"id": "old", "title": "Old", "duration": 5}))
    (directory / "transcript.json").write_text("[]")
    assert main([str(directory), "--at", "1"]) == 1
    assert "Source absente" in capsys.readouterr().err
    assert main([str(directory), "--at", "1", "--no-frames"]) == 0
    _result(capsys)
