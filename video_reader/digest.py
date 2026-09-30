"""Render the final Markdown digest and its JSON side files."""

from __future__ import annotations

import bisect
import json
import math
import os
import shlex
from pathlib import Path

from .models import FetchResult, Frame, Segment

DESCRIPTION_LIMIT = 600


def fmt_time(seconds: float | None) -> str:
    """MM:SS, or HH:MM:SS from one hour on; 'inconnue' when unknown."""
    if seconds is None:
        return "inconnue"
    hours, rest = divmod(max(int(seconds), 0), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _rel(path: Path | None, out_dir: Path) -> str | None:
    """Path relative to out_dir (posix style), or None if absent or outside out_dir."""
    if path is None:
        return None
    rel = os.path.relpath(path, out_dir).replace(os.sep, "/")
    return None if rel.startswith("..") else rel


def _blocks(
    meta: FetchResult, segments: list[Segment], frames: list[Frame], block_seconds: float
) -> list[tuple[float, str, bool]]:
    """Return (start, heading, keep_when_empty) for each block, ordered by start."""
    chapters = sorted((c for c in meta.chapters if "start_time" in c), key=lambda c: c["start_time"])
    if chapters:
        blocks = [
            (float(c["start_time"]), f"### [{fmt_time(c['start_time'])}] {c.get('title') or 'Chapitre'}", True)
            for c in chapters
        ]
        if blocks[0][0] > 0:
            blocks.insert(0, (0.0, f"### [00:00 - {fmt_time(blocks[0][0])}]", False))
        return blocks

    step = block_seconds if block_seconds > 0 else 60.0
    end = max([meta.duration or 0.0, *(s.end for s in segments), *(f.time for f in frames)])
    count = max(1, math.ceil(end / step))
    return [
        (i * step, f"### [{fmt_time(i * step)} - {fmt_time(min((i + 1) * step, end))}]", False)
        for i in range(count)
    ]


def _render_items(items: list[tuple[float, Frame | Segment]], out_dir: Path) -> list[str]:
    """Paragraphs of inline-timestamped segments, with frames at their chronological place."""
    lines: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            lines.append(" ".join(paragraph))
            paragraph.clear()

    for time, item in sorted(items, key=lambda it: (it[0], isinstance(it[1], Segment))):
        if isinstance(item, Frame):
            flush()
            path = _rel(item.path, out_dir) or item.path.name
            lines.append(f"![frame {fmt_time(time)}]({path})")
        else:
            text = " ".join(item.text.split())
            if text:
                paragraph.append(f"[{fmt_time(time)}] {text}")
    flush()
    return lines


def _transcript_source(meta: FetchResult, segments: list[Segment]) -> str | None:
    if not segments:
        return None
    return "sous-titres" if meta.subtitle_path else "transcription automatique (whisper)"


def _header(meta: FetchResult, segments: list[Segment], frames: list[Frame]) -> list[str]:
    lines = [f"# {meta.title}", ""]
    lines.append(f"- Auteur : {meta.uploader or 'inconnu'}")
    lines.append(f"- Durée : {fmt_time(meta.duration)}")
    if meta.url:
        lines.append(f"- Source : {meta.url}")
    lines.append(f"- Frames : {len(frames)}")
    lines.append(f"- Segments de transcription : {len(segments)}")
    source = _transcript_source(meta, segments)
    if source:
        lines.append(f"- Source de la transcription : {source}")

    description = (meta.description or "").strip()
    if description:
        if len(description) > DESCRIPTION_LIMIT:
            description = description[:DESCRIPTION_LIMIT].rstrip() + "..."
        lines += ["", "## Description", ""]
        lines += [f"> {line}".rstrip() for line in description.splitlines()]

    chapters = sorted((c for c in meta.chapters if "start_time" in c), key=lambda c: c["start_time"])
    if chapters:
        lines += ["", "## Chapitres", ""]
        lines += [f"- [{fmt_time(c['start_time'])}] {c.get('title') or 'Chapitre'}" for c in chapters]
    return lines


def _body(
    meta: FetchResult, segments: list[Segment], frames: list[Frame], out_dir: Path, block_seconds: float
) -> list[str]:
    lines = ["", "## Contenu", ""]
    if not segments:
        lines += ["Aucune transcription disponible.", ""]

    blocks = _blocks(meta, segments, frames, block_seconds)
    starts = [b[0] for b in blocks]
    grouped: list[list[tuple[float, Frame | Segment]]] = [[] for _ in blocks]
    for seg in segments:
        grouped[max(bisect.bisect_right(starts, seg.start) - 1, 0)].append((seg.start, seg))
    for frame in frames:
        grouped[max(bisect.bisect_right(starts, frame.time) - 1, 0)].append((frame.time, frame))

    for (_, heading, keep_empty), items in zip(blocks, grouped):
        if not items and not keep_empty:
            continue
        lines += [heading, ""]
        for line in _render_items(items, out_dir):
            lines += [line, ""]
    return lines


_NOTES = [
    "## Notes pour l'IA",
    "",
    "- Les images de la vidéo sont dans le dossier `frames/` (chemins relatifs à ce fichier) : "
    "ouvrez-les avec l'outil de lecture d'images pour voir la vidéo.",
    "- Le nom de chaque image contient son timestamp ; les timestamps `[mm:ss]` du texte "
    "permettent de relier la parole à l'image la plus proche.",
    "- Ne déduisez rien qui ne figure ni dans la transcription ni dans les images.",
]


def render(
    meta: FetchResult,
    segments: list[Segment],
    frames: list[Frame],
    out_dir: Path,
    block_seconds: float = 60.0,
    *,
    source: str | None = None,
) -> Path:
    """Write digest.md, transcript.json and meta.json into out_dir; return the digest path."""
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = _header(meta, segments, frames)
    lines += _body(meta, segments, frames, out_dir, block_seconds)
    lines += _NOTES
    command_source = shlex.quote(str(out_dir.resolve()))
    lines += [
        "", "## Naviguer dans la vidéo", "",
        "Pour examiner un autre moment, relancez l'outil sur ce dossier. Chaque commande "
        "produit un nouveau rapport `inspection.md` et ses images sans modifier ce digest.",
        "", "```sh",
        f"video-reader {command_source} --at 00:05 --context 5",
        f"video-reader {command_source} --start 00:00 --end 00:10 --interval 1",
        "```", "",
        "Adaptez les timestamps à la durée de la vidéo. Formats : secondes, MM:SS ou HH:MM:SS "
        "avec millisecondes facultatives. Plusieurs instants : `--at 00:01 00:03.500`.",
        "Si la vidéo distante n'est pas en cache, elle sera téléchargée à nouveau ; "
        "`--keep-video` la conserve pour les prochaines consultations. "
        "Un fichier local doit rester à son emplacement d'origine.",
    ]
    digest_path = out_dir / "digest.md"
    digest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    transcript = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
    (out_dir / "transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    info = {
        "id": meta.id,
        "title": meta.title,
        "uploader": meta.uploader,
        "duration": meta.duration,
        "url": meta.url,
        "source": source or meta.url,
        "description": meta.description,
        "chapters": meta.chapters,
        "subtitle_path": _rel(meta.subtitle_path, out_dir),
        "video_path": _rel(meta.video_path, out_dir),
        "audio_path": _rel(meta.audio_path, out_dir),
        "frame_count": len(frames),
        "segment_count": len(segments),
        "transcript_source": _transcript_source(meta, segments),
    }
    (out_dir / "meta.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return digest_path
