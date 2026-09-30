---
name: video-reader
description: Watch, navigate, analyze or summarize a video from a URL or local file using its transcript and images. Freely seek to timestamps, jump back, compare moments and inspect short ranges. Use when the user gives a video link or path and asks what it shows or says, wants a summary, notes, a specific moment, or a question answered about the video.
argument-hint: <url-or-path> [question]
---

# video-reader

Turn a video into a digest (timestamped transcript + key frames) that you can read, then answer the user's request from it.

Arguments: `$ARGUMENTS` = the video URL or file path, optionally followed by the user's question. Without a question, produce a structured summary with the main points and their timestamps.

## Steps

1. Check the tool is available: `video-reader --help`. If missing, install it with `pip install -e <repo root>` (this repository) or `pip install git+https://github.com/tromset/video-reader-ai`. Add `[whisper]` (for example `pip install -e "<repo root>[whisper]"`) when audio transcription is needed.

2. Run `video-reader "<url-or-path>" --keep-video` to prepare an overview and cache remote video for follow-up navigation.
   - `--lang fr,en` sets the subtitle languages in order of preference (default `en,fr`): put the user's or the video's language first.
   - Add `--whisper` when the video has no subtitles (the tool warns on stderr).
   - The last line printed on stdout is the absolute path of `digest.md`. Progress logs go to stderr.
   - Remember the absolute directory containing `digest.md`: use it as `SOURCE` for follow-up commands. Local videos remain at their original path and are never moved or copied.
   - If the user already identifies a moment, you may start directly with `video-reader "<url-or-path>" --at 01:23 --keep-video`. It returns `inspection.md` under `<video directory>/inspections/seek-*/`; use that video directory for further queries.

3. Read `digest.md` with Read. If it is very long, read it in chunks with `offset` and `limit`.

4. Look at the frames: the digest embeds them as `![frame mm:ss](frames/xxx.jpg)`, relative to the digest folder. Open them with Read (it displays images).
   - 12 frames or fewer: open all of them.
   - More: open a sample targeted at the question (the frames around the relevant timestamps, plus a few evenly spread ones for an overview).

5. Navigate as needed; you are not limited to the overview's sampled frames. Choose timestamps yourself based on the user's question, chapters, transcript and images already seen:
   - Seek to a moment: `video-reader "<video directory>" --at 01:23.500 --context 5`.
   - Jump backwards or compare moments: `video-reader "<video directory>" --at 02:10 00:45 01:23.500`. Requested order is preserved; nearby timestamps are not dropped.
   - Inspect an action more closely: `video-reader "<video directory>" --start 01:20 --end 01:30 --interval 1`. Narrow the range or lower the interval for more detail, respecting `--max-frames` (default 40). If capped, samples span the range and the report says so.
   - Times accept seconds, `MM:SS` or `HH:MM:SS`, with optional milliseconds. Range start is inclusive and end exclusive. Adapt all examples to the video's duration; do not request an instant at or beyond its end.
   - Read the returned `inspection.md`, then open its referenced images. `inspection.json` contains requested timestamps, frame paths, transcript windows and original transcript segments for structured use. Text includes whole segments overlapping the selected window.
   - Repeat this observe → choose timestamp → inspect loop until the passage is understood or the evidence is insufficient. Look before and after an event when a single frame does not explain it. Do not ask the user for each navigation choice.
   - Inspections preserve the digest and earlier reports. Use the prepared directory or its `digest.md`, not the original URL, for subsequent queries. If the video was not cached, add `--keep-video` once to avoid repeated downloads. Credentials must be supplied again if needed.
   - Seeking is limited by source frame rate: requested milliseconds do not guarantee an image captured at that exact millisecond. Never claim continuous viewing based only on sparse still images.

6. Answer the user's request:
   - Cite timestamps as `[mm:ss]` (or `[hh:mm:ss]`) for each claim.
   - Rely only on the transcript and the frames you opened. If something is not there (silent part, frame not opened, no transcript), say so instead of guessing.
   - Mention when the transcript is missing or automatic (whisper), since it may contain errors.

## Troubleshooting

- Download blocked, age-restricted, private or unavailable video: the error is printed as `error: ...`. Try `pip install -U yt-dlp`. If YouTube answers "Sign in to confirm you're not a bot" or the video needs a login, rerun with `--cookies-from-browser chrome` (or `firefox`, `safari`...) or `--cookies cookies.txt`; if that is impossible here, tell the user. Never invent the content.
- No subtitles: rerun with `--whisper` (needs the `whisper` extra; use `--whisper-model base` for speed or `medium` for accuracy).
- Long video: lower the cost with `--max-frames 20` and a larger `--interval 60` or `--block 120`, then read only the relevant parts of the digest.
- Audio only or frames not needed: `--no-frames` skips the video download; omit `--keep-video`. On a prepared digest it allows transcript-only navigation without the media.
- Output goes to `./video-reader-output/<video id>/` by default (`--out DIR` to change it). Preparing the original source again overwrites the overview; navigation on a prepared directory creates a new inspection each time and ignores `--out`.
- An existing digest's transcript is reused. To add missing transcription, rerun the original source with `--whisper --keep-video`.
- An out-of-range or undecodable timestamp is an error: choose a valid earlier moment using the known duration instead of inventing an image. Old local digests without a source path must be regenerated from the video file.
