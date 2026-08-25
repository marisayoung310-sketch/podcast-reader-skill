#!/usr/bin/env python3
"""Transcribe permitted local media to timestamped JSONL using a local backend."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def faster_whisper(source: Path, output: Path, model: str, language: str | None) -> None:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit("Install faster-whisper in the active Python environment") from exc
    engine = WhisperModel(model, compute_type="int8")
    segments, _ = engine.transcribe(str(source), language=language, vad_filter=True)
    with output.open("w", encoding="utf-8") as handle:
        for segment in segments:
            handle.write(json.dumps({"start_ms": round(segment.start * 1000), "end_ms": round(segment.end * 1000), "text": segment.text.strip()}, ensure_ascii=False) + "\n")


def whisper_cpp(source: Path, output: Path, model: str, language: str | None) -> None:
    binary = shutil.which("whisper-cli") or shutil.which("main")
    if not binary:
        raise SystemExit("Install whisper.cpp and expose whisper-cli (or main) on PATH")
    with tempfile.TemporaryDirectory() as temp:
        prefix = Path(temp) / "transcript"
        command = [binary, "-m", model, "-f", str(source), "-oj", "-of", str(prefix)]
        if language: command += ["-l", language]
        subprocess.run(command, check=True)
        payload = json.loads(prefix.with_suffix(".json").read_text(encoding="utf-8"))
        rows = payload.get("transcription") or payload.get("segments") or []
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                offsets = row.get("offsets", {})
                start = offsets.get("from", row.get("start", 0))
                end = offsets.get("to", row.get("end"))
                if isinstance(start, float): start = round(start * 1000)
                if isinstance(end, float): end = round(end * 1000)
                handle.write(json.dumps({"start_ms": int(start), "end_ms": int(end) if end is not None else None, "text": (row.get("text") or "").strip()}, ensure_ascii=False) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path); p.add_argument("output", type=Path)
    p.add_argument("--backend", choices=["faster-whisper", "whisper-cpp"], default="faster-whisper")
    p.add_argument("--model", default="small"); p.add_argument("--language")
    args = p.parse_args(); args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.backend == "faster-whisper": faster_whisper(args.source, args.output, args.model, args.language)
    else: whisper_cpp(args.source, args.output, args.model, args.language)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

