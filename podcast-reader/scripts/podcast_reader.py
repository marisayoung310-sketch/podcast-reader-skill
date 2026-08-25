#!/usr/bin/env python3
"""Local podcast inbox and timestamped transcript store (standard library only)."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

UA = "podcast-reader-skill/0.1 (+local personal reader)"


def fetch(url: str, accept: str = "*/*") -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=25) as response:
        return response.read(), response.geturl()


def db_connect(data: Path) -> sqlite3.Connection:
    data.mkdir(parents=True, exist_ok=True)
    (data / "transcripts").mkdir(exist_ok=True)
    (data / "notes").mkdir(exist_ok=True)
    (data / "media").mkdir(exist_ok=True)
    db = sqlite3.connect(data / "podcast.db")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS sources (
          id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL,
          feed_url TEXT NOT NULL UNIQUE, original_url TEXT, created_at TEXT NOT NULL,
          last_synced TEXT
        );
        CREATE TABLE IF NOT EXISTS episodes (
          id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id),
          guid TEXT NOT NULL, title TEXT NOT NULL, description TEXT, published TEXT,
          duration INTEGER, original_url TEXT, media_url TEXT, image_url TEXT,
          discovered_at TEXT NOT NULL, played INTEGER NOT NULL DEFAULT 0,
          UNIQUE(source_id, guid)
        );
        CREATE TABLE IF NOT EXISTS segments (
          episode_id TEXT NOT NULL REFERENCES episodes(id), seq INTEGER NOT NULL,
          start_ms INTEGER NOT NULL, end_ms INTEGER, speaker TEXT, text TEXT NOT NULL,
          PRIMARY KEY(episode_id, seq)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS segment_fts USING fts5(
          episode_id UNINDEXED, seq UNINDEXED, text, tokenize='unicode61'
        );
        """
    )
    return db


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def text_of(node: ET.Element | None, default: str = "") -> str:
    return (node.text or "").strip() if node is not None else default


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def children(node: ET.Element, name: str) -> list[ET.Element]:
    return [x for x in node.iter() if local_name(x.tag) == name.lower()]


def first(node: ET.Element, names: Iterable[str]) -> ET.Element | None:
    wanted = {n.lower() for n in names}
    return next((x for x in node.iter() if local_name(x.tag) in wanted), None)


def clean_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def parse_duration(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    try:
        parts = [int(p) for p in value.split(":")]
        total = 0
        for part in parts:
            total = total * 60 + part
        return total
    except ValueError:
        return None


def parse_date(value: str) -> str | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(value).astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return value


def meta(html_text: str, key: str) -> str | None:
    patterns = [
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return None


def discover_feed(url: str) -> dict[str, str]:
    raw = url.strip()
    if re.fullmatch(r"UC[\w-]{20,}", raw):
        return {"kind": "youtube", "title": raw, "feed_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={raw}", "original_url": raw}
    if "youtube.com/feeds/videos.xml" in raw:
        return {"kind": "youtube", "title": "YouTube channel", "feed_url": raw, "original_url": raw}

    body, final_url = fetch(raw, "application/rss+xml, application/atom+xml, text/xml, text/html")
    probe = body[:500].lstrip()
    if probe.startswith(b"<?xml") or probe.startswith(b"<rss") or probe.startswith(b"<feed"):
        root = ET.fromstring(body)
        title = text_of(first(root, ["title"]), "Podcast")
        return {"kind": "youtube" if "youtube.com" in final_url else "rss", "title": title, "feed_url": final_url, "original_url": raw}

    page = body.decode("utf-8", "replace")
    channel = re.search(r'"channelId"\s*:\s*"(UC[\w-]+)"', page)
    if "youtube.com" in final_url and channel:
        cid = channel.group(1)
        return {"kind": "youtube", "title": meta(page, "og:title") or cid, "feed_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", "original_url": raw}

    rss_patterns = [
        r'<link[^>]+type=["\']application/(?:rss\+xml|atom\+xml)["\'][^>]+href=["\']([^"\']+)',
        r'"(?:rssUrl|feedUrl|feed_url)"\s*:\s*"(https?:[^"\\]+)',
    ]
    for pattern in rss_patterns:
        match = re.search(pattern, page, re.I)
        if match:
            feed_url = urllib.parse.urljoin(final_url, html.unescape(match.group(1)).replace("\\/", "/"))
            return {"kind": "rss", "title": meta(page, "og:title") or "Podcast", "feed_url": feed_url, "original_url": raw}

    if "spotify.com/show/" in final_url:
        title = meta(page, "og:title") or meta(page, "twitter:title")
        if title:
            query = urllib.parse.urlencode({"term": title, "media": "podcast", "entity": "podcast", "limit": 8})
            result, _ = fetch("https://itunes.apple.com/search?" + query, "application/json")
            candidates = json.loads(result).get("results", [])
            for candidate in candidates:
                if candidate.get("feedUrl"):
                    return {"kind": "rss", "title": candidate.get("collectionName", title), "feed_url": candidate["feedUrl"], "original_url": raw}
    raise ValueError("No public feed was found. Provide the publisher RSS URL or a canonical YouTube channel ID.")


def feed_entries(feed_url: str) -> tuple[str, list[dict]]:
    body, _ = fetch(feed_url, "application/rss+xml, application/atom+xml, text/xml")
    root = ET.fromstring(body)
    title = text_of(first(root, ["title"]), "Podcast")
    nodes = children(root, "item") or children(root, "entry")
    out = []
    for item in nodes:
        title_node = first(item, ["title"])
        title_value = clean_markup(text_of(title_node, "Untitled episode"))
        guid = text_of(first(item, ["guid", "id"]))
        links = [x for x in item.iter() if local_name(x.tag) in {"link", "enclosure"}]
        original = ""
        media = ""
        for link in links:
            href = link.attrib.get("href") or link.attrib.get("url") or text_of(link)
            rel = link.attrib.get("rel", "alternate")
            mime = link.attrib.get("type", "")
            if (rel == "enclosure" or mime.startswith(("audio/", "video/"))) and href:
                media = media or href
            elif href and rel in {"alternate", ""}:
                original = original or href
        original = original or text_of(first(item, ["link"]))
        guid = guid or original or hashlib.sha256((title_value + text_of(first(item, ["pubDate", "published", "updated"]))).encode()).hexdigest()
        description = text_of(first(item, ["encoded", "description", "summary", "content"]))
        duration = text_of(first(item, ["duration"]))
        image_node = first(item, ["image", "thumbnail"])
        image_url = image_node.attrib.get("href") or image_node.attrib.get("url") if image_node is not None else None
        out.append({
            "guid": guid, "title": title_value, "description": clean_markup(description),
            "published": parse_date(text_of(first(item, ["pubDate", "published", "updated"]))),
            "duration": parse_duration(duration), "original_url": original, "media_url": media,
            "image_url": image_url,
        })
    return title, out


def episode_id(source_id: int, guid: str) -> str:
    return hashlib.sha256(f"{source_id}:{guid}".encode()).hexdigest()[:16]


def cmd_add(db: sqlite3.Connection, url: str, name: str | None) -> None:
    info = discover_feed(url)
    title = name or info["title"]
    db.execute("INSERT OR IGNORE INTO sources(kind,title,feed_url,original_url,created_at) VALUES(?,?,?,?,?)", (info["kind"], title, info["feed_url"], info["original_url"], now()))
    db.commit()
    row = db.execute("SELECT * FROM sources WHERE feed_url=?", (info["feed_url"],)).fetchone()
    print(json.dumps(dict(row), ensure_ascii=False, indent=2))


def sync_one(db: sqlite3.Connection, source: sqlite3.Row) -> dict:
    title, entries = feed_entries(source["feed_url"])
    added = 0
    for entry in entries:
        eid = episode_id(source["id"], entry["guid"])
        cur = db.execute(
            "INSERT OR IGNORE INTO episodes(id,source_id,guid,title,description,published,duration,original_url,media_url,image_url,discovered_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (eid, source["id"], entry["guid"], entry["title"], entry["description"], entry["published"], entry["duration"], entry["original_url"], entry["media_url"], entry["image_url"], now()),
        )
        added += cur.rowcount
    db.execute("UPDATE sources SET title=?, last_synced=? WHERE id=?", (title or source["title"], now(), source["id"]))
    db.commit()
    return {"source_id": source["id"], "title": title, "found": len(entries), "added": added}


def format_time(seconds: int | None) -> str:
    if seconds is None:
        return ""
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def parse_timestamp(value: str) -> int:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    seconds = float(parts[-1])
    if len(parts) > 1:
        seconds += int(parts[-2]) * 60
    if len(parts) > 2:
        seconds += int(parts[-3]) * 3600
    return round(seconds * 1000)


def parse_transcript(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    if path.suffix.lower() in {".srt", ".vtt"}:
        blocks = re.split(r"\n\s*\n", raw.replace("\r", "\n"))
        segments = []
        for block in blocks:
            lines = [x.strip() for x in block.splitlines() if x.strip() and x.strip() != "WEBVTT"]
            timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if timing_index is None:
                continue
            start, end = [x.strip().split()[0] for x in lines[timing_index].split("-->")[:2]]
            text = clean_markup(" ".join(lines[timing_index + 1:]))
            if text:
                segments.append({"start_ms": parse_timestamp(start), "end_ms": parse_timestamp(end), "text": text})
        return segments
    segments = []
    for line in raw.splitlines():
        match = re.match(r"\s*\[?((?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?)\]?\s*(.*)", line)
        if match and match.group(2).strip():
            segments.append({"start_ms": parse_timestamp(match.group(1)), "end_ms": None, "text": match.group(2).strip()})
    return segments


def row_dict(row: sqlite3.Row) -> dict:
    value = dict(row)
    value["duration_text"] = format_time(value.get("duration"))
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("podcast-reader-data"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    add = sub.add_parser("add"); add.add_argument("url"); add.add_argument("--name")
    sync = sub.add_parser("sync"); sync.add_argument("--source", type=int)
    inbox = sub.add_parser("inbox"); inbox.add_argument("--days", type=int, default=7); inbox.add_argument("--limit", type=int, default=30)
    episode = sub.add_parser("episode"); episode.add_argument("id")
    status = sub.add_parser("transcript-status"); status.add_argument("id")
    imp = sub.add_parser("import-transcript"); imp.add_argument("id"); imp.add_argument("path", type=Path)
    search = sub.add_parser("search"); search.add_argument("id"); search.add_argument("query"); search.add_argument("--limit", type=int, default=8)
    export = sub.add_parser("export-context"); export.add_argument("id"); export.add_argument("--query"); export.add_argument("--limit", type=int, default=40)
    mark = sub.add_parser("mark"); mark.add_argument("id"); mark.add_argument("state", choices=["played", "unplayed"])
    args = parser.parse_args()
    db = db_connect(args.data)
    try:
        if args.command == "init":
            print(args.data.resolve())
        elif args.command == "add":
            cmd_add(db, args.url, args.name)
        elif args.command == "sync":
            query = "SELECT * FROM sources" + (" WHERE id=?" if args.source else "")
            rows = db.execute(query, (args.source,) if args.source else ()).fetchall()
            results = []
            for row in rows:
                try: results.append(sync_one(db, row))
                except Exception as exc: results.append({"source_id": row["id"], "title": row["title"], "error": str(exc)})
            print(json.dumps(results, ensure_ascii=False, indent=2))
        elif args.command == "inbox":
            cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).isoformat()
            rows = db.execute("SELECT e.*,s.title source_title,s.kind source_kind FROM episodes e JOIN sources s ON s.id=e.source_id WHERE COALESCE(e.published,e.discovered_at)>=? ORDER BY COALESCE(e.published,e.discovered_at) DESC LIMIT ?", (cutoff, args.limit)).fetchall()
            print(json.dumps([row_dict(x) for x in rows], ensure_ascii=False, indent=2))
        elif args.command == "episode":
            row = db.execute("SELECT e.*,s.title source_title,s.kind source_kind FROM episodes e JOIN sources s ON s.id=e.source_id WHERE e.id=?", (args.id,)).fetchone()
            if not row: raise ValueError("Episode not found")
            print(json.dumps(row_dict(row), ensure_ascii=False, indent=2))
        elif args.command == "transcript-status":
            count = db.execute("SELECT COUNT(*) FROM segments WHERE episode_id=?", (args.id,)).fetchone()[0]
            print(json.dumps({"episode_id": args.id, "segments": count, "ready": count > 0}))
        elif args.command == "import-transcript":
            segments = parse_transcript(args.path)
            if not segments: raise ValueError("No timestamped segments found")
            db.execute("DELETE FROM segments WHERE episode_id=?", (args.id,)); db.execute("DELETE FROM segment_fts WHERE episode_id=?", (args.id,))
            for seq, seg in enumerate(segments):
                db.execute("INSERT INTO segments VALUES(?,?,?,?,?,?)", (args.id, seq, int(seg["start_ms"]), seg.get("end_ms"), seg.get("speaker"), clean_markup(seg["text"])))
                db.execute("INSERT INTO segment_fts(episode_id,seq,text) VALUES(?,?,?)", (args.id, seq, clean_markup(seg["text"])))
            db.commit(); print(json.dumps({"episode_id": args.id, "segments": len(segments)}))
        elif args.command in {"search", "export-context"}:
            query = args.query if args.command == "export-context" else args.query
            if query:
                terms = [x for x in re.findall(r"[\w\u3400-\u9fff]+", query.lower()) if len(x) > 1]
                fts_query = " OR ".join(f'"{x}"' for x in terms[:12])
                rows = db.execute("SELECT s.* FROM segment_fts f JOIN segments s ON s.episode_id=f.episode_id AND s.seq=f.seq WHERE f.episode_id=? AND segment_fts MATCH ? ORDER BY bm25(segment_fts) LIMIT ?", (args.id, fts_query, args.limit)).fetchall() if fts_query else []
            else:
                rows = db.execute("SELECT * FROM segments WHERE episode_id=? ORDER BY seq LIMIT ?", (args.id, args.limit)).fetchall()
            payload = [{"timestamp": format_time(x["start_ms"] // 1000), **dict(x)} for x in rows]
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.command == "mark":
            db.execute("UPDATE episodes SET played=? WHERE id=?", (args.state == "played", args.id)); db.commit()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

