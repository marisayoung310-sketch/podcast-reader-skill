# Podcast Reader Skill

A local-first Codex skill that turns public podcast RSS feeds, YouTube channels, Spotify podcast links, and Xiaoyuzhou (小宇宙) links into a daily listening inbox with timestamped summaries and grounded Q&A.

## Why it is free to run

- No hosted backend and no bundled paid API.
- RSS metadata and the local inbox use Python's standard library.
- Transcription can run locally with Whisper.
- Summaries and questions use the user's existing Codex/ChatGPT session.
- Everything is cached in local SQLite and Markdown files.

Spotify and Xiaoyuzhou are treated as discovery/playback links. The skill analyzes an episode only when it can resolve a publisher's public RSS/transcript or when the user supplies media they are allowed to process.

## Install

Clone the repository and copy or symlink `podcast-reader` into your Codex skills directory:

```bash
git clone https://github.com/marisayoung310-sketch/podcast-reader-skill.git
mkdir -p ~/.codex/skills
ln -s "$PWD/podcast-reader-skill/podcast-reader" ~/.codex/skills/podcast-reader
```

Restart Codex, then try:

```text
Use $podcast-reader to follow this podcast RSS feed and show me this week's new episodes.
```

Or:

```text
Use $podcast-reader to analyze this YouTube interview, produce a timeline, and explain what the guest means at 18:32.
```

## Optional local transcription

Install either `faster-whisper` or `whisper.cpp`. Install `yt-dlp` only when you need to prepare public YouTube subtitles or media you have permission to process. The skill never installs dependencies automatically and does not bypass paywalls, DRM, login requirements, or private feeds.

## Repository layout

```text
podcast-reader/
├── SKILL.md
├── agents/openai.yaml
├── references/
└── scripts/
```

## License

MIT
