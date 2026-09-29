"""Command line entrypoint: video-reader SOURCE [options]."""

from __future__ import annotations

import argparse
import contextlib
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .digest import render
from .fetch import fetch
from .frames import extract_frames
from .models import Segment, VideoReaderError
from .transcript import load_segments, transcribe


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-reader",
        description="Turn a video (URL or local file) into a digest for an AI: transcript + key frames.",
    )
    p.add_argument("source", help="video URL (anything yt-dlp supports) or local file path")
    p.add_argument("--out", type=Path, default=Path("video-reader-output"), help="output root (default: ./video-reader-output)")
    p.add_argument("--lang", default="en,fr", help="preferred subtitle languages, comma separated (default: en,fr)")
    p.add_argument("--max-frames", type=int, default=40, help="maximum number of frames (default: 40)")
    p.add_argument("--interval", type=float, default=30.0, help="seconds between fallback frames (default: 30)")
    p.add_argument("--scene-threshold", type=float, default=0.3, help="scene change sensitivity, 0-1 (default: 0.3)")
    p.add_argument("--block", type=float, default=60.0, help="seconds per digest block (default: 60)")
    p.add_argument("--whisper", action="store_true", help="transcribe the audio with whisper when there are no subtitles")
    p.add_argument("--whisper-model", default="small", help="whisper model size (default: small)")
    p.add_argument("--cookies", help="Netscape cookies.txt file for sites that require sign-in")
    p.add_argument("--cookies-from-browser", metavar="BROWSER", help="load cookies from a local browser (chrome, firefox, safari...)")
    p.add_argument("--no-frames", action="store_true", help="skip video download and frame extraction")
    return p


def _run(args: argparse.Namespace) -> Path:
    out_root: Path = args.out.expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    langs = [lang.strip() for lang in args.lang.split(",") if lang.strip()]

    # The video id is only known after fetch, so fetch into a private temporary
    # directory inside the output root, then build out/<id>. The temporary directory
    # is always removed at the end: it holds every downloaded file and nothing else.
    # A local file given by the user lives outside it and is never touched.
    workdir = Path(tempfile.mkdtemp(prefix=".work-", dir=out_root))
    try:
        _log("Récupération de la vidéo...")
        meta = fetch(
            args.source,
            workdir,
            langs,
            need_video=not args.no_frames,
            need_audio=args.whisper,
            cookies=args.cookies,
            cookies_from_browser=args.cookies_from_browser,
        )
        out_dir = out_root / (re.sub(r"[^\w.-]", "_", meta.id).strip(".") or "video")
        out_dir.mkdir(parents=True, exist_ok=True)

        segments: list[Segment] = []
        if meta.subtitle_path:
            _log("Lecture des sous-titres...")
            segments = load_segments(meta.subtitle_path)
        elif args.whisper and meta.audio_path:
            _log(f"Transcription avec whisper ({args.whisper_model})...")
            segments = transcribe(meta.audio_path, args.whisper_model)
        else:
            _log("Avertissement : Pas de sous-titres ; relancez avec --whisper")

        frames = []
        if not args.no_frames and meta.video_path:
            _log("Extraction des images...")
            frames_dir = out_dir / "frames"
            shutil.rmtree(frames_dir, ignore_errors=True)  # drop frames from a previous run
            frames = extract_frames(
                meta.video_path, frames_dir, args.max_frames, args.interval, args.scene_threshold
            )

        _log("Écriture du digest...")
        digest = render(meta, segments, frames, out_dir, args.block)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    _log(f"{len(segments)} segments, {len(frames)} images.")
    return digest.resolve()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        # Keep stdout clean: third-party libraries may print, only the digest path may reach it.
        with contextlib.redirect_stdout(sys.stderr):
            digest = _run(args)
    except VideoReaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return 130
    print(digest)
    return 0

