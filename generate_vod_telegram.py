#!/usr/bin/env python3
"""
Telegram VOD Playlist Generator
Reads all forwarded video messages sent directly to the bot.
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


def get_all_videos():
    videos = []
    offset = 0

    log.info("Fetching all messages sent to bot...")

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

            # Get video or document
            video = msg.get("video") or msg.get("document")
            if not video:
                continue

            # Check if it's a video file
            mime = video.get("mime_type", "")
            if not mime.startswith("video/"):
                continue

            # Use caption or filename as name
            name = msg.get("caption", "") or video.get("file_name", f"Video_{msg.get('message_id', '')}")
            file_id = video.get("file_id", "")

            if file_id:
                videos.append({
                    "name": Path(name).stem,
                    "file_id": file_id,
                })
                log.info("  Found: %s", name)

    return videos


def generate_m3u(videos, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in sorted(videos, key=lambda x: x["name"]):
            url = get_file_url(item["file_id"])
            if not url:
                log.warning("  Skipping %s — could not get URL", item["name"])
                continue
            f.write(f'#EXTINF:-1 tvg-name="{item["name"]}" group-title="{ROOT_GROUP}",{item["name"]}\n')
            f.write(url + "\n")
            count += 1
    size_kb = output_path.stat().st_size / 1024
    log.info("Written %d item(s) to %s (%.1f KB).", count, output_path, size_kb)


def main():
    log.info("=== Telegram VOD Playlist Generator started ===")

    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN not set.")
        sys.exit(1)

    videos = get_all_videos()
    log.info("Found %d video(s) total.", len(videos))

    if not videos:
        log.warning("No videos found. Make sure you forwarded videos to the bot.")

    generate_m3u(videos, OUTPUT_FILE)
    log.info("=== Done! ===")


if __name__ == "__main__":
    main()
