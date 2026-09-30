# video-reader-ai

It turns any video into digestible for AI, just put the URL and use the /video-reader skill to make AI watch videos.

## What it produces

For each video, `video-reader` writes a folder that an AI can read directly:

```
video-reader-output/<video id>/
  digest.md         header, chapters, then transcript blocks with frames in chronological order
  transcript.json   list of {start, end, text} segments (seconds)
  meta.json         title, uploader, duration, url, description, chapters
  frames/           key frames, e.g. 0001_00-00-01.jpg (index and timestamp in the name)
  media/            cached video, only with --keep-video (remote sources)
  inspections/      one separate folder per timestamp/range query, with Markdown, JSON and frames
```

`digest.md` references the frames with relative paths (`![frame 01:06](frames/0002_00-01-06.jpg)`), so an AI that can open images can "see" the video.

## Installation

Requires Python 3.10 or newer. ffmpeg is bundled through `imageio-ffmpeg`.

```
pip install -e .
pip install -e ".[whisper]"   # optional: local transcription with faster-whisper
```

## CLI usage

```
video-reader SOURCE [options]
python -m video_reader SOURCE [options]
```

`SOURCE` is a URL supported by yt-dlp (YouTube and many other sites), a local video file, or an existing output directory / `digest.md` for navigation. On success the absolute path of `digest.md` (or `inspection.md` for navigation) is printed on stdout; progress and warnings go to stderr.

| Option | Default | Meaning |
| --- | --- | --- |
| `--out DIR` | `./video-reader-output` | Output root; results go to `DIR/<video id>/` |
| `--lang fr,en` | `en,fr` | Subtitle languages, in order of preference |
| `--max-frames N` | `40` | Maximum frames; ranges are sampled across their full extent to respect this limit; an oversized `--at` list is rejected |
| `--interval S` | `30` | Seconds between fallback frames or range samples (at least `0.001`) |
| `--scene-threshold X` | `0.3` | Scene change sensitivity (0 to 1, lower means more frames) |
| `--block S` | `60` | Seconds per block in the digest (ignored when the video has chapters) |
| `--whisper` | off | Transcribe the audio with whisper when there are no subtitles |
| `--whisper-model M` | `small` | Whisper model size |
| `--no-frames` | off | Skip the video download and frame extraction |
| `--keep-video` | off | Keep downloaded video for future navigation; local files are referenced, never moved or copied |
| `--at TIME [TIME ...]` | none | Inspect one or more timestamps, in the requested order; may be repeated |
| `--start TIME --end TIME` | none | Inspect a range from start (inclusive) to end (exclusive), sampled with `--interval` |
| `--context TIME` | `5` | Transcript seconds before and after each `--at` timestamp; `0` returns only segments active at that instant |
| `--cookies FILE` | none | Netscape cookies.txt for sites that require sign-in |
| `--cookies-from-browser B` | none | Load cookies from a local browser (`chrome`, `firefox`, `safari`...), e.g. when YouTube asks to confirm you are not a bot |

Example:

```
video-reader "https://www.youtube.com/watch?v=VIDEO_ID" --lang fr,en --max-frames 20
```

## Navigate freely by timestamp

Start with an overview and keep the remote media available for quick follow-up queries:

```sh
video-reader "https://www.youtube.com/watch?v=VIDEO_ID" --keep-video

# Open a moment with nearby speech, including cues that began before the window.
video-reader "video-reader-output/VIDEO_ID" --at 01:23.500 --context 5

# Compare moments, or jump backwards; the requested order is preserved.
video-reader "video-reader-output/VIDEO_ID/digest.md" --at 02:10 00:45 01:23.500

# Examine a short sequence more closely: one image per second.
video-reader "video-reader-output/VIDEO_ID" --start 01:20 --end 01:30 --interval 1

# A direct request also works without generating an overview of all frames first.
video-reader "./demo.mp4" --at 4.100 4.200 --keep-video
```

Times accept seconds (`83.5`), `MM:SS` (`01:23.500`) or `HH:MM:SS` (`01:02:03.250`), with up to three decimal places. Instants must be before the end of the video; the exclusive range end may equal its duration. `--at` and `--start/--end` cannot be combined. Images are obtained by seeking, without scanning the entire video for scene changes. Their timestamps are requested positions, with precision limited by the video's frame rate. An undecodable position produces an explicit error, including near the very end of a video.

Every query creates `inspections/seek-*/inspection.md`, `inspection.json`, and its own `frames/` inside the video's output folder. Read the returned Markdown path, then open its images. The JSON includes the requested timestamps, transcript windows, frame paths and original transcript segments. Overlapping segments are kept whole; no words or timing are invented. Range sampling is capped at `--max-frames` and the report says when the cap applies. No scene deduplication drops closely spaced `--at` requests.

When reopening a prepared digest, its overview, original frames, and transcript stay intact; `--out` is ignored and reports stay beside the digest. The transcript is reused: to add Whisper transcription, rerun the original source with `--whisper`. A raw URL or video path still starts a new preparation and overwrites its overview. Read-only transcript navigation is also possible with `--no-frames`, even when the original video is unavailable.

Without `--keep-video`, a remote source is downloaded again when images are requested; add `--keep-video` to that follow-up to cache it. A missing cache falls back to the recorded source. Supply cookies again if required: cookie settings are not stored. Cached media consumes disk space and can be deleted by removing that output folder's `media/` directory. Local source files must remain at their original path. Older URL digests can fall back to their `url`; older local digests without a recorded source must be regenerated.

## Claude Code skill

The skill lives in `.claude/skills/video-reader/` of this repository. Inside the repo, ask Claude Code:

```
/video-reader <url-or-path> [question]
```

Claude runs the tool, reads the digest, opens relevant frames, and uses timestamp queries to investigate or revisit any passage before answering with timestamps. To use the skill from any project, copy the folder into your personal skills directory:

```
cp -r .claude/skills/video-reader ~/.claude/skills/
```

## How it works

1. yt-dlp downloads the metadata, the subtitles and, unless `--no-frames` is set, the video (a local file is used as is).
2. The transcript comes from the subtitles; without subtitles, `--whisper` transcribes the audio locally.
3. ffmpeg extracts frames on scene changes, completed by one frame every `--interval` seconds, capped at `--max-frames`.
4. The digest merges transcript and frames chronologically, grouped by chapter or by fixed-length blocks.

Downloaded media are deleted at the end unless `--keep-video` retains the video; a local file you pass in is never removed. Navigation reuses the local source or cached video and extracts only the requested frames.

## Tests

```
pip install -e ".[dev]" && pytest
```
