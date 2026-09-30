"""Reopen prepared videos and produce focused, non-destructive inspections."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .frames import extract_at
from .models import FetchResult, Segment, VideoReaderError
from .timestamps import format_timestamp


@dataclass
class Selection:
    times: list[float]
    windows: list[tuple[float, float]]
    start: float | None
    end: float | None
    context: float
    capped: bool = False


def select(
    at: list[float] | None,
    start: float | None,
    end: float | None,
    context: float,
    interval: float,
    max_frames: int,
    duration: float | None,
) -> Selection:
    """Validate bounds before extraction and bound sampling work for long ranges."""
    if at:
        times = list(dict.fromkeys(at))  # preserve the agent's requested order
        if len(times) > max_frames:
            raise VideoReaderError("Trop de timestamps : augmentez --max-frames ou réduisez --at.")
        if duration is not None and any(t >= duration for t in times):
            raise VideoReaderError(f"Timestamp hors vidéo : utilisez un instant < {duration:g} s.")
        windows = [
            (max(0.0, t - context), min(duration, t + context) if duration is not None else t + context)
            for t in times
        ]
        return Selection(times, windows, None, None, context)
    if start is None or end is None or end <= start:
        raise VideoReaderError("La plage exige --start et --end, avec end > start.")
    if duration is not None and (start >= duration or end > duration):
        raise VideoReaderError(f"Plage hors vidéo : la durée est de {duration:g} s.")
    steps = (end - start) / interval
    if not math.isfinite(steps):
        raise VideoReaderError("La plage demandée est trop grande.")
    count = max(1, math.ceil(steps))
    capped = count > max_frames
    if capped:
        indices = ([0] if max_frames == 1 else
                   [round(i * (count - 1) / (max_frames - 1)) for i in range(max_frames)])
    else:
        indices = range(count)
    times = list(dict.fromkeys(round(start + i * interval, 3) for i in indices
                               if round(start + i * interval, 3) < end))
    return Selection(times, [(start, end)], start, end, 0.0, capped)


def session_directory(source: str) -> Path | None:
    if "://" in source:
        return None
    path = Path(source).expanduser()
    if path.is_dir():
        return path.resolve()
    if path.name == "digest.md" and path.is_file():
        return path.resolve().parent
    return None


def load_session(out_dir: Path) -> tuple[FetchResult, list[Segment], str | None, str | None]:
    try:
        info = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        transcript = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
        duration = info.get("duration")
        if duration is not None:
            duration = float(duration)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("durée invalide")
        segments = [Segment(float(s["start"]), float(s["end"]), s["text"]) for s in transcript]
        if any(not math.isfinite(s.start) or not math.isfinite(s.end) or
               s.start < 0 or s.end < s.start or not isinstance(s.text, str) for s in segments):
            raise ValueError("transcription invalide")
        source = info.get("source") or info.get("url")
        if source is not None and not isinstance(source, str):
            raise ValueError("source invalide")
        video = None
        if info.get("video_path"):
            cached = (out_dir / info["video_path"]).resolve()
            if not cached.is_relative_to(out_dir.resolve()):
                raise ValueError("le cache vidéo doit rester dans le dossier du digest")
            if cached.is_file():
                video = cached
        if video is None and source and "://" not in source:
            local = Path(source).expanduser()
            if local.is_file():
                video = local.resolve()
        meta = FetchResult(
            id=info["id"], title=info["title"], uploader=info.get("uploader"),
            duration=duration, url=info.get("url"), description=info.get("description"),
            chapters=info.get("chapters") or [], video_path=video,
        )
        return meta, segments, source, info.get("transcript_source")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise VideoReaderError(f"Digest illisible dans {out_dir} : {exc}") from exc


def keep_video(meta: FetchResult, workdir: Path, out_dir: Path) -> None:
    """Move only our downloaded media into the cache; never move a user's file."""
    if meta.video_path is None or not meta.video_path.resolve().is_relative_to(workdir.resolve()):
        return
    media_dir = out_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / f"video{meta.video_path.suffix}"
    shutil.move(str(meta.video_path), target)
    meta.video_path = target


def inspect(
    meta: FetchResult,
    segments: list[Segment],
    out_dir: Path,
    selection: Selection,
    transcript_source: str | None,
    no_frames: bool = False,
) -> Path:
    """Write one isolated report per query, preserving the original digest."""
    selected = sorted([
        s for s in segments if any(
            (s.start <= start < s.end if start == end else s.end > start and s.start < end)
            for start, end in selection.windows
        )
    ], key=lambda s: s.start)
    parent = out_dir / "inspections"
    parent.mkdir(parents=True, exist_ok=True)
    report_dir = Path(tempfile.mkdtemp(prefix="seek-", dir=parent))
    try:
        frames = []
        if not no_frames:
            if meta.video_path is None:
                raise VideoReaderError("Vidéo indisponible pour extraire des images.")
            frames = extract_at(meta.video_path, report_dir / "frames", selection.times)
        data = {
            "title": meta.title,
            "duration": meta.duration,
            "mode": "range" if selection.start is not None else "at",
            "requested_timestamps": selection.times,
            "start": selection.start,
            "end": selection.end,
            "context_seconds": selection.context,
            "transcript_windows": [{"start": a, "end": b} for a, b in selection.windows],
            "sampling_capped": selection.capped,
            "transcript_source": transcript_source,
            "frames": [{"requested_time": f.time, "path": f.path.relative_to(report_dir).as_posix()}
                       for f in frames],
            "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in selected],
        }
        lines = [f"# Navigation — {meta.title}", "", "[Digest complet](../../digest.md)", ""]
        if selection.start is not None:
            lines += [f"Plage : [{format_timestamp(selection.start)} – "
                      f"{format_timestamp(selection.end)}[ (fin exclue).", ""]
        else:
            lines += ["Instants demandés : " + ", ".join(format_timestamp(t) for t in selection.times),
                      f"Contexte de transcription : ±{selection.context:g} s.", ""]
        if selection.capped:
            lines += ["Échantillonnage réparti sur la plage pour respecter --max-frames. "
                      "Resserrez la plage ou augmentez cette limite pour voir plus de détails.", ""]
        lines += ["## Images", ""]
        if no_frames:
            lines += ["Extraction des images désactivée (--no-frames).", ""]
        else:
            lines += ["Les timestamps indiquent les positions demandées ; les images dépendent "
                      "de la cadence de la vidéo. Ouvrez les fichiers pour les examiner.", ""]
        for frame in data["frames"]:
            lines += [f"![frame {format_timestamp(frame['requested_time'])}]({frame['path']})", ""]
        lines += ["## Transcription du passage", ""]
        if transcript_source:
            lines += [f"Source : {transcript_source}.", ""]
        if selected:
            lines += ["Les segments qui chevauchent la fenêtre sont conservés en entier, "
                      "avec leurs timestamps d'origine.", ""]
            for seg in selected:
                lines += [f"[{format_timestamp(seg.start)} – {format_timestamp(seg.end)}] "
                          + " ".join(seg.text.split()), ""]
        else:
            lines += ["Aucune transcription disponible pour ce passage.", ""]
        (report_dir / "inspection.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report = report_dir / "inspection.md"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report
    except Exception:
        shutil.rmtree(report_dir, ignore_errors=True)
        raise
