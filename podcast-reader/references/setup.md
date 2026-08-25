# Setup and source behavior

## Core

`podcast_reader.py` requires Python 3.10+ and uses only the standard library. Its SQLite database, transcripts, media, and notes remain inside the selected `--data` directory.

## Optional media tools

Install only what is needed:

- `yt-dlp`: retrieve public YouTube metadata and available subtitles; audio preparation requires the explicit `--allow-audio` flag.
- `ffmpeg`: normalize media for transcription.
- `whisper.cpp`: local, lightweight transcription through a `whisper-cli` or `main` binary.
- `faster-whisper`: local Python transcription, generally faster with supported hardware.

The scripts detect installed commands and print an actionable error when none are available. They do not install software automatically.

## Source resolution

### RSS

Use the feed directly. Public RSS enclosures are the preferred podcast audio source.

### YouTube

Accept a channel ID, channel feed URL, channel URL, or video URL. Channel page resolution may fail when YouTube changes its HTML. In that case, use the canonical channel ID (`UC...`) or feed URL:

`https://www.youtube.com/feeds/videos.xml?channel_id=UC...`

Available captions are preferred. Do not use cookies or signed-in extraction unless the user explicitly authorizes access to their own content and understands the platform terms.

### Spotify

Spotify links are metadata pointers, not generic audio-download URLs. The resolver reads public page metadata and queries Apple's public podcast catalog for a matching publisher RSS feed. Because names can collide, verify the resolved show title before processing. Platform-exclusive shows may have no public RSS and should remain playback-only.

### Xiaoyuzhou / 小宇宙

The resolver looks for a public RSS link exposed by the page. If none exists, retain the link for playback and ask the user for the publisher RSS. Do not request or store Xiaoyuzhou login tokens.

## Local transcription examples

Whisper.cpp:

```bash
python3 scripts/transcribe_local.py input.mp3 output.jsonl --backend whisper-cpp --model /path/to/ggml-small.bin
```

Faster Whisper:

```bash
python3 scripts/transcribe_local.py input.mp3 output.jsonl --backend faster-whisper --model small
```

Choose `tiny` or `base` on low-memory machines, `small` for a balanced default, and larger models only when the user accepts slower processing.

