"""Shared data contract between pipeline modules. Do not change without updating all modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class VideoReaderError(Exception):
    """User-facing error with a clear message."""


@dataclass
class Segment:
    start: float  # seconds
    end: float  # seconds
    text: str


@dataclass
class Frame:
    time: float  # seconds
    path: Path


@dataclass
class FetchResult:
    id: str
    title: str
    uploader: str | None
    duration: float | None  # seconds
    url: str | None
    description: str | None
    chapters: list[dict] = field(default_factory=list)  # [{"title": str, "start_time": float, "end_time": float}]
    subtitle_path: Path | None = None
    video_path: Path | None = None
    audio_path: Path | None = None
