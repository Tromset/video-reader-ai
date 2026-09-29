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

`SOURCE` is a URL supported by yt-dlp (YouTube and many other sites) or a local video file. On success the absolute path of `digest.md` is printed on stdout; progress and warnings go to stderr.

| Option | Default | Meaning |
| --- | --- | --- |
| `--out DIR` | `./video-reader-output` | Output root; results go to `DIR/<video id>/` |
| `--lang fr,en` | `en,fr` | Subtitle languages, in order of preference |
| `--max-frames N` | `40` | Maximum number of frames |
| `--interval S` | `30` | Seconds between frames when no scene change is detected |
| `--scene-threshold X` | `0.3` | Scene change sensitivity (0 to 1, lower means more frames) |
| `--block S` | `60` | Seconds per block in the digest (ignored when the video has chapters) |
| `--whisper` | off | Transcribe the audio with whisper when there are no subtitles |
| `--whisper-model M` | `small` | Whisper model size |
| `--no-frames` | off | Skip the video download and frame extraction |
| `--cookies FILE` | none | Netscape cookies.txt for sites that require sign-in |
| `--cookies-from-browser B` | none | Load cookies from a local browser (`chrome`, `firefox`, `safari`...), e.g. when YouTube asks to confirm you are not a bot |

Example:

```
video-reader "https://www.youtube.com/watch?v=VIDEO_ID" --lang fr,en --max-frames 20
```

## Claude Code skill

The skill lives in `.claude/skills/video-reader/` of this repository. Inside the repo, ask Claude Code:

```
/video-reader <url-or-path> [question]
```

Claude runs the tool, reads the digest, opens the relevant frames and answers your question with timestamps. To use the skill from any project, copy the folder into your personal skills directory:

```
cp -r .claude/skills/video-reader ~/.claude/skills/
```

## How it works

1. yt-dlp downloads the metadata, the subtitles and, unless `--no-frames` is set, the video (a local file is used as is).
2. The transcript comes from the subtitles; without subtitles, `--whisper` transcribes the audio locally.
3. ffmpeg extracts frames on scene changes, completed by one frame every `--interval` seconds, capped at `--max-frames`.
4. The digest merges transcript and frames chronologically, grouped by chapter or by fixed-length blocks.

Downloaded media are deleted at the end; a local file you pass in is never removed.

## Tests

```
pip install -e ".[dev]" && pytest
```
