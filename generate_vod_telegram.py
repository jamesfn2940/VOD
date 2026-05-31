#!/usr/bin/env python3
"""
Telegram VOD Playlist Generator
Saves video file_ids to a JSON database so they persist across runs.
"""

import json
import os
import sys
import logging
import urllib.request
import urllib.parse
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
OUTPUT_FILE = Path(os.environ.get("VOD_OUTPUT_FILE", "vod_playlist.m3u"))
DB_FILE     = Path(os.environ.get("VOD_DB_FILE", "vod_database.json"))
ROOT_GROUP  = os.environ.get("VOD_GROUP", "VOD")


def api_call(method, params=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.error("API error: %s", e)
        return {"ok": False}


def get_file_url(file_id):
    result = api_call("getFile", {"file_id": file_id})
    if not result.get("ok"):
        return None
    file_path = result["result"]["file_path"]
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


def load_database():
    """Load existing video database."""
    if DB_FILE.exists():
        with DB_FILE.open() as f:
            return json.load(f)
    return {}


def save_database(db):
    """Save video database to JSON file."""
    with DB_FILE.open("w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    log.info("Database saved: %d video(s).", len(db))


def fetch_new_videos(db):
    """Fetch new videos from bot updates and add to database."""
    new_count = 0
    offset = 0

    log.info("Checking for new videos...")

    while True:
        result = api_call("getUpdates", {
            "offset": offset,
            "limit": 100,
        })

        if not result.get("ok"):
            log.error("Failed to get updates: %s", result)
            break

        updates = result.get("result", [])
        if not updates:
            break

        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})

            video = msg.get("video") or msg.get("document")
            if not video:
                continue

            mime = video.get("mime_type", "")
            if not mime.startswith("video/"):
                continue

            name = msg.get("caption", "") or video.get("file_name", f"Video_{msg.get('message_id', '')}")
            file_id = video.get("file_id", "")
            name = Path(name).stem

            if file_id and file_id not in db:
                db[file_id] = {"name": name, "group": ROOT_GROUP}
                log.info("  New video: %s", name)
                new_count += 1

        # Mark updates as read
        if updates:
            api_call("getUpdates", {"offset": offset, "limit": 1})

    log.info("Found %d new video(s).", new_count)
    return db


def generate_m3u(db, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for file_id, info in sorted(db.items(), key=lambda x: x[1]["name"]):
            url = get_file_url(file_id)
            if not url:
                log.warning("  Skipping %s — could not get URL", info["name"])
                continue
            group = info.get("group", ROOT_GROUP)
            name = info["name"]
            f.write(f'#EXTINF:-1 tvg-name="{name}" group-title="{group}",{name}\n')
            f.write(url + "\n")
            count += 1
    size_kb = output_path.stat().st_size / 1024
    log.info("Written %d item(s) to %s (%.1f KB).", count, output_path, size_kb)


def main():
    log.info("=== Telegram VOD Playlist Generator started ===")

    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set.")
        sys.exit(1)

    # Load existing database
    db = load_database()
    log.info("Loaded %d existing video(s) from database.", len(db))

    # Fetch new videos
    db = fetch_new_videos(db)

    # Save updated database
    save_database(db)

    if not db:
        log.warning("No videos in database. Forward videos to the bot first.")

    # Generate M3U
    generate_m3u(db, output_path=OUTPUT_FILE)
    log.info("=== Done! ===")


if __name__ == "__main__":
    main()
