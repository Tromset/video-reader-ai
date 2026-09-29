"""ffmpeg helpers: binary lookup, duration probing."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .models import VideoReaderError

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def get_ffmpeg() -> str:
    """Return the path of an ffmpeg binary (system first, then imageio-ffmpeg)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # ImportError or RuntimeError when no binary is bundled
        raise VideoReaderError(
            "ffmpeg introuvable : installez ffmpeg ou `pip install imageio-ffmpeg`."
        ) from exc


def probe_duration(path: Path) -> float | None:
    """Duration in seconds parsed from `ffmpeg -i` stderr, or None if unknown."""
    proc = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    match = _DURATION_RE.search(proc.stderr)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)
