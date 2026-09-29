---
name: video-reader
description: Watch, analyze or summarize a video from a URL (YouTube and any site supported by yt-dlp) or a local video file, using its timestamped transcript and key frames. Use when the user gives a video link or path and asks what it shows or says, wants a summary, notes, a specific moment, or a question answered about the video.
argument-hint: <url-or-path> [question]
---

# video-reader

Turn a video into a digest (timestamped transcript + key frames) that you can read, then answer the user's request from it.

Arguments: `$ARGUMENTS` = the video URL or file path, optionally followed by the user's question. Without a question, produce a structured summary with the main points and their timestamps.

## Steps

1. Check the tool is available: `video-reader --help`. If missing, install it with `pip install -e <repo root>` (this repository) or `pip install git+https://github.com/tromset/video-reader-ai`. Add `[whisper]` (for example `pip install -e "<repo root>[whisper]"`) when audio transcription is needed.

2. Run `video-reader "<url-or-path>"`.
   - `--lang fr,en` sets the subtitle languages in order of preference (default `en,fr`): put the user's or the video's language first.
   - Add `--whisper` when the video has no subtitles (the tool warns on stderr).
   - The last line printed on stdout is the absolute path of `digest.md`. Progress logs go to stderr.

3. Read `digest.md` with Read. If it is very long, read it in chunks with `offset` and `limit`.

4. Look at the frames: the digest embeds them as `![frame mm:ss](frames/xxx.jpg)`, relative to the digest folder. Open them with Read (it displays images).
   - 12 frames or fewer: open all of them.
   - More: open a sample targeted at the question (the frames around the relevant timestamps, plus a few evenly spread ones for an overview).

5. Answer the user's request:
   - Cite timestamps as `[mm:ss]` (or `[hh:mm:ss]`) for each claim.
   - Rely only on the transcript and the frames you opened. If something is not there (silent part, frame not opened, no transcript), say so instead of guessing.
   - Mention when the transcript is missing or automatic (whisper), since it may contain errors.

## Troubleshooting

- Download blocked, age-restricted, private or unavailable video: the error is printed as `error: ...`. Try `pip install -U yt-dlp`. If YouTube answers "Sign in to confirm you're not a bot" or the video needs a login, rerun with `--cookies-from-browser chrome` (or `firefox`, `safari`...) or `--cookies cookies.txt`; if that is impossible here, tell the user. Never invent the content.
- No subtitles: rerun with `--whisper` (needs the `whisper` extra; use `--whisper-model base` for speed or `medium` for accuracy).
- Long video: lower the cost with `--max-frames 20` and a larger `--interval 60` or `--block 120`, then read only the relevant parts of the digest.
- Audio only or frames not needed: `--no-frames` skips the video download.
- Output goes to `./video-reader-output/<video id>/` by default (`--out DIR` to change it); rerunning overwrites it.
