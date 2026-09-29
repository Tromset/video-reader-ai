"""Fetch a video source (yt-dlp URL or local file): metadata, subtitles, media."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .ffmpeg import get_ffmpeg, probe_duration
from .models import FetchResult, VideoReaderError

_VIDEO_FORMAT = "bv*[height<=480]+ba/b[height<=480]/b"
_AUDIO_FORMAT = "ba/b"
_SUB_EXTS = ("vtt", "srt")


def fetch(
    source: str,
    workdir: Path,
    langs: list[str],
    need_video: bool,
    need_audio: bool = False,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
) -> FetchResult:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    local = Path(source).expanduser()
    if local.is_file():
        return _fetch_local(local, workdir, langs, need_audio)
    if "://" in source or source.startswith("www."):
        return _fetch_url(
            source, workdir, langs, need_video, need_audio, cookies, cookies_from_browser
        )
    raise VideoReaderError(f"Fichier introuvable (et ce n'est pas une URL) : {source}")


# --- local files ---------------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "video"


def _extract_audio(media: Path, workdir: Path) -> Path:
    """Write a 16 kHz mono wav (what whisper wants) from any media file."""
    out = workdir / "audio.wav"
    proc = subprocess.run(
        [get_ffmpeg(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
         "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", str(out)],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if proc.returncode != 0 or not out.exists():
        raise VideoReaderError(
            f"Impossible d'extraire l'audio de {media.name} : {proc.stderr.strip()[-300:]}"
        )
    return out


def _sidecar_subtitles(video: Path, langs: list[str]) -> Path | None:
    for ext in _SUB_EXTS:
        for suffix in ("", *(f".{lang}" for lang in langs)):
            candidate = video.with_name(f"{video.stem}{suffix}.{ext}")
            if candidate.is_file():
                return candidate
    return None


def _fetch_local(path: Path, workdir: Path, langs: list[str], need_audio: bool) -> FetchResult:
    return FetchResult(
        id=_slug(path.stem),
        title=path.name,
        uploader=None,
        duration=probe_duration(path),
        url=None,
        description=None,
        subtitle_path=_sidecar_subtitles(path, langs),
        video_path=path,
        audio_path=_extract_audio(path, workdir) if need_audio else None,
    )


# --- yt-dlp --------------------------------------------------------------------


def _pick_track(tracks: dict[str, list[dict]], langs: list[str]) -> tuple[str, list[dict]] | None:
    """First language of `langs` matching a track key (exact or by prefix: en -> en-US)."""
    for lang in langs:
        lang = lang.lower()
        for key, formats in tracks.items():
            k = key.lower()
            if formats and (k == lang or k.startswith(lang + "-")):
                return key, formats
    return None


def _choose_subtitles(info: dict, langs: list[str]) -> tuple[str, list[dict]] | None:
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    for tracks in (manual, auto):
        picked = _pick_track(tracks, langs)
        if picked:
            return picked
    # No requested language: fall back to the original language, then anything.
    original = (info.get("language") or "").lower()
    if original:
        for tracks in (manual, auto):
            picked = _pick_track(tracks, [original])
            if picked:
                return picked
    for tracks in (manual, auto):
        # Prefer "<lang>-orig" auto tracks (untranslated speech recognition).
        keys = sorted(tracks, key=lambda k: not k.endswith("-orig"))
        for key in keys:
            if tracks[key]:
                return key, tracks[key]
    return None


def _download_subtitles(ydl, info: dict, langs: list[str], workdir: Path) -> Path | None:
    picked = _choose_subtitles(info, langs)
    if not picked:
        return None
    lang, formats = picked
    for ext in _SUB_EXTS:
        for fmt in formats:
            if fmt.get("ext") == ext and fmt.get("url"):
                try:
                    data = ydl.urlopen(fmt["url"]).read()
                except Exception:  # network/HTTP error on the track: continue without subtitles
                    return None
                path = workdir / f"subtitles.{lang}.{ext}"
                path.write_bytes(data)
                return path
    return None


def _find_download(workdir: Path, stem: str) -> Path | None:
    files = [
        p for p in workdir.glob(f"{stem}.*")
        if p.suffix not in (".part", ".ytdl", ".temp") and p.is_file()
    ]
    return max(files, key=lambda p: p.stat().st_size, default=None)


class _SilentLogger:
    def debug(self, msg: str) -> None:
        pass

    info = warning = error = debug


def _fetch_url(
    url: str,
    workdir: Path,
    langs: list[str],
    need_video: bool,
    need_audio: bool,
    cookies: str | None = None,
    cookies_from_browser: str | None = None,
) -> FetchResult:
    import yt_dlp
    from yt_dlp.utils import DownloadError

    base_opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "logger": _SilentLogger(),  # errors surface once, as VideoReaderError
    }
    if cookies:  # needed when the site asks to sign in (e.g. YouTube bot check)
        base_opts["cookiefile"] = str(Path(cookies).expanduser())
    if cookies_from_browser:
        base_opts["cookiesfrombrowser"] = (cookies_from_browser,)
    try:
        with yt_dlp.YoutubeDL(base_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise VideoReaderError(f"Aucune information trouvée pour : {url}")
            subtitle_path = _download_subtitles(ydl, info, langs, workdir)

        video_path = audio_path = None
        if need_video or need_audio:
            stem = "video" if need_video else "audio"
            opts = {
                **base_opts,
                "format": _VIDEO_FORMAT if need_video else _AUDIO_FORMAT,
                "outtmpl": str(workdir / f"{stem}.%(ext)s"),
                "ffmpeg_location": get_ffmpeg(),
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([info.get("webpage_url") or url])
            downloaded = _find_download(workdir, stem)
            if downloaded is None:
                raise VideoReaderError(f"Téléchargement terminé mais fichier introuvable dans {workdir}")
            if need_video:
                video_path = downloaded
                if need_audio:
                    audio_path = _extract_audio(downloaded, workdir)
            else:
                audio_path = downloaded
    except DownloadError as exc:
        msg = re.sub(r"^ERROR:\s*", "", str(exc)).strip()
        raise VideoReaderError(f"Téléchargement impossible pour {url} : {msg}") from exc

    return FetchResult(
        id=str(info.get("id") or _slug(url)),
        title=info.get("title") or str(info.get("id") or url),
        uploader=info.get("uploader") or info.get("channel"),
        duration=float(info["duration"]) if info.get("duration") else (
            probe_duration(video_path or audio_path) if (video_path or audio_path) else None
        ),
        url=info.get("webpage_url") or url,
        description=info.get("description"),
        chapters=[
            {"title": c.get("title", ""), "start_time": c.get("start_time", 0.0), "end_time": c.get("end_time")}
            for c in info.get("chapters") or []
        ],
        subtitle_path=subtitle_path,
        video_path=video_path,
        audio_path=audio_path,
    )
