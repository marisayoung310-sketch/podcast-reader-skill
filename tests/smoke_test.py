#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "podcast-reader" / "scripts" / "podcast_reader.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run(data: Path, *args: str) -> str:
    result = subprocess.run([sys.executable, str(SCRIPT), "--data", str(data), *args], check=True, text=True, capture_output=True)
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        run(data, "init")
        run(data, "add", (FIXTURES / "feed.xml").as_uri())
        synced = json.loads(run(data, "sync"))
        assert synced[0]["added"] == 1
        inbox = json.loads(run(data, "inbox", "--days", "3650"))
        assert len(inbox) == 1 and inbox[0]["duration"] == 754
        eid = inbox[0]["id"]
        imported = json.loads(run(data, "import-transcript", eid, str(FIXTURES / "transcript.srt")))
        assert imported["segments"] == 3
        found = json.loads(run(data, "search", eid, "model usage user account"))
        assert found and found[0]["timestamp"] == "00:10"
    print("smoke test passed")


if __name__ == "__main__":
    main()
