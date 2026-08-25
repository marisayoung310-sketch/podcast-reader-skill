#!/usr/bin/env python3
"""Prepare subtitles or audio from a public episode without bypassing access controls."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("url")
    p.add_argument("output", type=Path)
    p.add_argument("--allow-audio", action="store_true", help="Explicitly permit audio download for content you may process")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    if "youtube.com" in args.url or "youtu.be" in args.url:
        if not shutil.which("yt-dlp"):
            raise SystemExit("yt-dlp is required for YouTube subtitle preparation")
        base = ["yt-dlp", "--no-playlist", "--paths", str(args.output), "--write-subs", "--write-auto-subs", "--sub-langs", "en.*,zh.*,ja.*", "--sub-format", "vtt"]
        if args.allow_audio:
            base += ["-x", "--audio-format", "mp3"]
        else:
            base += ["--skip-download"]
        subprocess.run(base + [args.url], check=True)
        return 0

    if not args.allow_audio:
        raise SystemExit("RSS audio preparation requires --allow-audio after confirming permission")
    target = args.output / "episode-audio"
    req = urllib.request.Request(args.url, headers={"User-Agent": "podcast-reader-skill/0.1"})
    with urllib.request.urlopen(req, timeout=60) as src, target.open("wb") as dst:
        shutil.copyfileobj(src, dst)
    print(json.dumps({"path": str(target.resolve()), "content_type": src.headers.get("Content-Type")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

