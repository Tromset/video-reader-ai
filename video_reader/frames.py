"""Key frame extraction: scene changes + regular sampling, deduplicated."""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from .ffmpeg import get_ffmpeg, probe_duration
from .models import Frame, VideoReaderError

_PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")
_MIN_GAP = 2.0


def _scene_times(video_path: Path, threshold: float) -> list[float]:
    # fps=2 keeps scene detection fast on long videos.
    vf = f"fps=2,select='gt(scene,{threshold})',showinfo"
    proc = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-nostdin", "-i", str(video_path),
         "-vf", vf, "-vsync", "vfr", "-an", "-f", "null", "-"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0:
        return []
    return [float(m) for m in _PTS_RE.findall(proc.stderr)]


def _dedupe(times: list[float], min_gap: float = _MIN_GAP) -> list[float]:
    kept: list[float] = []
    for t in sorted(times):
        if not kept or t - kept[-1] >= min_gap:
            kept.append(t)
    return kept


def _subsample(times: list[float], n: int) -> list[float]:
    if len(times) <= n:
        return times
    if n == 1:
        return times[:1]
    step = (len(times) - 1) / (n - 1)
    return [times[round(i * step)] for i in range(n)]


def _fmt(t: float) -> str:
    s = int(t)
    return f"{s // 3600:02d}-{s % 3600 // 60:02d}-{s % 60:02d}"


def _extract_frame(video_path: Path, path: Path, time: float) -> bool:
    proc = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-ss", f"{time:.3f}", "-i", str(video_path), "-frames:v", "1",
         "-vf", "scale='min(768,iw)':-2", "-q:v", "3", str(path)],
        capture_output=True,
    )
    if proc.returncode == 0 and path.exists() and path.stat().st_size > 0:
        return True
    path.unlink(missing_ok=True)
    return False


def extract_at(video_path: Path, out_dir: Path, times: list[float]) -> list[Frame]:
    """Seek to every requested time, without scene detection or two-second dedupe.

    Timestamps are seek positions; the image is the first decodable frame at or
    after that position, subject to the source frame rate. Missing frames fail
    explicitly instead of silently substituting an unrelated key frame.
    """
    if not video_path.is_file():
        raise VideoReaderError(f"Fichier vidéo introuvable : {video_path}")
    if any(not math.isfinite(t) or t < 0 for t in times):
        raise VideoReaderError("Les timestamps doivent être positifs ou nuls et finis.")
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, time in enumerate(times, 1):
        milliseconds = round(time * 1000)
        path = out_dir / f"{i:04d}_{_fmt(milliseconds / 1000)}-{milliseconds % 1000:03d}.jpg"
        if not _extract_frame(video_path, path, time):
            raise VideoReaderError(
                f"Aucune image décodable à {time:.3f} s ; vérifiez la durée et la piste vidéo."
            )
        frames.append(Frame(time=time, path=path))
    return frames


def extract_frames(
    video_path: Path,
    out_dir: Path,
    max_frames: int = 40,
    interval: float = 30.0,
    scene_threshold: float = 0.3,
) -> list[Frame]:
    if not math.isfinite(interval) or interval <= 0:
        raise VideoReaderError("L'intervalle doit être strictement positif et fini.")
    video_path = Path(video_path)
    if not video_path.is_file():
        raise VideoReaderError(f"Fichier vidéo introuvable : {video_path}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(video_path)
    last = max(duration - 0.5, 0.0) if duration else None

    start = 1.0 if duration is None or duration > 3 else 0.0
    regular: list[float] = []
    t = start
    while last is not None and t <= last:
        regular.append(t)
        t += interval
    scenes = [t for t in _scene_times(video_path, scene_threshold) if last is None or t <= last]

    # Sorted union; the first candidate (near the start) always survives dedupe.
    candidates = _dedupe([start, *regular, *scenes])
    candidates = _subsample(candidates, max(max_frames, 1))

    frames: list[Frame] = []
    for i, t in enumerate(candidates, 1):
        path = out_dir / f"{i:04d}_{_fmt(t)}.jpg"
        if _extract_frame(video_path, path, t):
            frames.append(Frame(time=t, path=path))
    return frames
