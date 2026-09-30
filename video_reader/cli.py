"""Command line entrypoint: video-reader SOURCE [options]."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .digest import render
from .fetch import fetch
from .frames import extract_frames
from .models import Segment, VideoReaderError
from .navigation import Selection, inspect, keep_video, load_session, select, session_directory
from .timestamps import parse_timestamp
from .transcript import load_segments, transcribe


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _timestamp(value: str) -> float:
    try:
        return parse_timestamp(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("la valeur doit être strictement positive et finie")
    return number


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-reader",
        description="Turn a video (URL or local file) into a digest for an AI: transcript + key frames.",
    )
    p.add_argument("source", help="video URL, local video, or existing digest.md / output directory")
    p.add_argument("--out", type=Path, default=Path("video-reader-output"), help="output root (default: ./video-reader-output)")
    p.add_argument("--lang", default="en,fr", help="preferred subtitle languages, comma separated (default: en,fr)")
    p.add_argument("--max-frames", type=int, default=40, help="maximum number of frames (default: 40)")
    p.add_argument("--interval", type=_positive, default=30.0, help="seconds between fallback/range frames (default: 30)")
    p.add_argument("--scene-threshold", type=float, default=0.3, help="scene change sensitivity, 0-1 (default: 0.3)")
    p.add_argument("--block", type=_positive, default=60.0, help="seconds per digest block (default: 60)")
    p.add_argument("--whisper", action="store_true", help="transcribe the audio with whisper when there are no subtitles")
    p.add_argument("--whisper-model", default="small", help="whisper model size (default: small)")
    p.add_argument("--cookies", help="Netscape cookies.txt file for sites that require sign-in")
    p.add_argument("--cookies-from-browser", metavar="BROWSER", help="load cookies from a local browser (chrome, firefox, safari...)")
    p.add_argument("--no-frames", action="store_true", help="skip video download and frame extraction")
    p.add_argument("--keep-video", action="store_true", help="cache downloaded video for later timestamp navigation")
    p.add_argument("--at", nargs="+", action="extend", type=_timestamp, metavar="TIME",
                   help="inspect one or more timestamps (seconds, MM:SS or HH:MM:SS; milliseconds allowed)")
    p.add_argument("--start", type=_timestamp, metavar="TIME", help="start of a range to inspect (inclusive)")
    p.add_argument("--end", type=_timestamp, metavar="TIME", help="end of a range to inspect (exclusive)")
    p.add_argument("--context", type=_timestamp, default=5.0, metavar="TIME",
                   help="transcript context on each side of --at (default: 5 seconds; 0 = active segment)")
    return p


def _selection(args: argparse.Namespace, duration: float | None) -> Selection:
    return select(args.at, args.start, args.end, args.context, args.interval, args.max_frames, duration)


def _revisit(args: argparse.Namespace, out_dir: Path) -> Path:
    if not args.at and args.start is None:
        raise VideoReaderError("Pour naviguer dans un digest, utilisez --at ou --start avec --end.")
    meta, segments, source, transcript_source = load_session(out_dir)
    selection = _selection(args, meta.duration)
    with tempfile.TemporaryDirectory(prefix=".work-", dir=out_dir) as temp:
        if not args.no_frames and meta.video_path is None:
            if not source:
                raise VideoReaderError("Source absente de cet ancien digest ; relancez avec l'URL ou le fichier vidéo.")
            _log("Vidéo absente du cache : récupération de la source...")
            fetched = fetch(
                source, Path(temp), [s.strip() for s in args.lang.split(",") if s.strip()],
                need_video=True, cookies=args.cookies, cookies_from_browser=args.cookies_from_browser,
            )
            meta.video_path = fetched.video_path
            if fetched.duration is not None:
                meta.duration = fetched.duration
                selection = _selection(args, meta.duration)
            if args.keep_video:
                keep_video(meta, Path(temp), out_dir)
                if meta.video_path and meta.video_path.is_relative_to(out_dir):
                    meta_path = out_dir / "meta.json"
                    info = json.loads(meta_path.read_text(encoding="utf-8"))
                    info["video_path"] = meta.video_path.relative_to(out_dir).as_posix()
                    info["duration"] = meta.duration
                    meta_path.write_text(json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _log("Inspection des passages demandés...")
        return inspect(meta, segments, out_dir, selection, transcript_source, args.no_frames).resolve()


def _run(args: argparse.Namespace) -> Path:
    prepared = session_directory(args.source)
    if prepared is not None:
        return _revisit(args, prepared)
    out_root: Path = args.out.expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    langs = [lang.strip() for lang in args.lang.split(",") if lang.strip()]

    # The video id is only known after fetch, so fetch into a private temporary
    # directory inside the output root, then build out/<id>. The temporary directory
    # is always removed at the end; --keep-video moves downloaded video out first.
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
        targeted = bool(args.at) or args.start is not None
        selection = _selection(args, meta.duration) if targeted else None

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
        if not targeted and not args.no_frames and meta.video_path:
            _log("Extraction des images...")
            frames_dir = out_dir / "frames"
            shutil.rmtree(frames_dir, ignore_errors=True)  # drop frames from a previous run
            frames = extract_frames(
                meta.video_path, frames_dir, args.max_frames, args.interval, args.scene_threshold
            )

        if args.keep_video:
            keep_video(meta, workdir, out_dir)
        local = Path(args.source).expanduser()
        source = str(local.resolve()) if local.is_file() else args.source
        _log("Écriture du digest...")
        digest = render(meta, segments, frames, out_dir, args.block, source=source)
        if selection is not None:
            _log("Inspection des passages demandés...")
            transcript_source = "sous-titres" if meta.subtitle_path else (
                "transcription automatique (whisper)" if segments else None
            )
            digest = inspect(meta, segments, out_dir, selection, transcript_source, args.no_frames)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    _log("Inspection terminée." if targeted else f"{len(segments)} segments, {len(frames)} images.")
    return digest.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.max_frames < 1:
        parser.error("--max-frames doit être au moins 1")
    if not math.isfinite(args.scene_threshold) or not 0 <= args.scene_threshold <= 1:
        parser.error("--scene-threshold doit être compris entre 0 et 1")
    if args.interval < 0.001:
        parser.error("--interval doit être au moins 0.001 seconde")
    if args.at and (args.start is not None or args.end is not None):
        parser.error("--at ne se combine pas avec --start/--end")
    if (args.start is None) != (args.end is None):
        parser.error("--start et --end doivent être fournis ensemble")
    if args.start is not None and args.end <= args.start:
        parser.error("--end doit être supérieur à --start")
    if args.keep_video and args.no_frames:
        parser.error("--keep-video ne se combine pas avec --no-frames")
    try:
        # Keep stdout clean: third-party libraries may print, only the digest path may reach it.
        with contextlib.redirect_stdout(sys.stderr):
            digest = _run(args)
    except VideoReaderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrompu.", file=sys.stderr)
        return 130
    print(digest)
    return 0
