"""Transcript loading (VTT/SRT subtitles) and optional Whisper transcription."""

from __future__ import annotations

import html
import re
from pathlib import Path

from .models import Segment, VideoReaderError

_TIME = r"(?:(\d+):)?(\d+):(\d+)[.,](\d+)"
_CUE_RE = re.compile(rf"{_TIME}\s*-->\s*{_TIME}")
_TAG_RE = re.compile(r"<[^>]*>")
_SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")

_MAX_SEGMENT = 15.0  # seconds
_MIN_SEGMENT = 3.0  # seconds before a punctuation break is accepted
_MAX_GAP = 2.0  # silence that forces a break


def _seconds(h: str | None, m: str, s: str, frac: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(frac) / 10 ** len(frac)


def _clean(line: str) -> str:
    line = html.unescape(_TAG_RE.sub("", line)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", line).strip()


def _parse_cues(content: str) -> list[tuple[float, float, list[str]]]:
    """Return (start, end, lines) for each cue of a VTT or SRT file."""
    cues: list[tuple[float, float, list[str]]] = []
    current: tuple[float, float, list[str]] | None = None
    for raw in content.splitlines():
        match = _CUE_RE.search(raw)
        if match:  # settings after the end time (align:start ...) are ignored
            g = match.groups()
            current = (_seconds(*g[:4]), _seconds(*g[4:]), [])
            cues.append(current)
        elif not raw.strip():
            current = None
        elif current is not None:
            line = _clean(raw)
            if line:
                current[2].append(line)
    return cues


def _dedupe_cues(cues: list[tuple[float, float, list[str]]]) -> list[Segment]:
    """Drop lines already shown in the previous cue (YouTube rolling auto-subs)."""
    segments: list[Segment] = []
    prev_lines: list[str] = []
    for start, end, lines in cues:
        new: list[str] = []
        for line in lines:
            if line in prev_lines:
                continue
            for old in prev_lines:  # single-line rolling captions: strip the emitted prefix
                if line.startswith(old + " "):
                    line = line[len(old) :].strip()
                    break
            new.append(line)
        if lines:
            prev_lines = lines
        text = " ".join(new).strip()
        if text and end - start >= 0.001:
            segments.append(Segment(start, end, text))
    return segments


def _merge(segments: list[Segment]) -> list[Segment]:
    """Join short segments into sentence-sized ones."""
    merged: list[Segment] = []
    cur: Segment | None = None
    for seg in segments:
        if cur is not None and seg.start - cur.end > _MAX_GAP:
            merged.append(cur)
            cur = None
        if cur is None:
            cur = Segment(seg.start, seg.end, seg.text)
        else:
            cur = Segment(cur.start, max(cur.end, seg.end), f"{cur.text} {seg.text}")
        duration = cur.end - cur.start
        if duration >= _MAX_SEGMENT or (
            cur.text.endswith(_SENTENCE_END) and duration >= _MIN_SEGMENT
        ):
            merged.append(cur)
            cur = None
    if cur is not None:
        merged.append(cur)
    return merged


def load_segments(subtitle_path: Path) -> list[Segment]:
    path = Path(subtitle_path)
    try:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise VideoReaderError(f"Sous-titres illisibles : {path} ({exc})") from exc
    segments = _dedupe_cues(_parse_cues(content))
    return sorted(_merge(segments), key=lambda s: s.start)


def transcribe(audio_path: Path, model: str = "small") -> list[Segment]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise VideoReaderError(
            "faster-whisper n'est pas installé : pip install 'video-reader-ai[whisper]'"
        ) from exc
    if not Path(audio_path).is_file():
        raise VideoReaderError(f"Fichier audio introuvable : {audio_path}")
    whisper = WhisperModel(model, device="auto", compute_type="int8")
    raw_segments, _info = whisper.transcribe(str(audio_path), vad_filter=True)
    return [
        Segment(seg.start, seg.end, seg.text.strip())
        for seg in raw_segments
        if seg.text.strip()
    ]
