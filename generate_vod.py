#!/usr/bin/env python3
"""
Google Drive VOD Playlist Generator
Reads all MP4/MKV files from a Google Drive folder and generates an M3U playlist.
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

API_KEY       = os.environ.get("GDRIVE_API_KEY", "")
FOLDER_ID     = os.environ.get("GDRIVE_FOLDER_ID", "")
OUTPUT_FILE   = Path(os.environ.get("VOD_OUTPUT_FILE", "vod_playlist.m3u"))
GROUP_LABEL   = os.environ.get("VOD_GROUP", "VOD")
VIDEO_EXTS    = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m4v"}


def list_files(folder_id, api_key):
    """List all video files in a Google Drive folder."""
    files = []
    page_token = None

    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,mimeType)",
            "pageSize": "1000",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            log.error("Failed to list files: %s", e)
            sys.exit(1)

        for f in data.get("files", []):
            ext = Path(f["name"]).suffix.lower()
            if ext in VIDEO_EXTS:
                files.append(f)

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return files


def make_stream_url(file_id, api_key):
    return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={api_key}"


def generate_m3u(files, output_path, group, api_key):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in sorted(files, key=lambda x: x["name"]):
            name = Path(item["name"]).stem  # Remove extension from display name
            url  = make_stream_url(item["id"], api_key)
            f.write(f'#EXTINF:-1 tvg-name="{name}" group-title="{group}",{name}\n')
            f.write(url + "\n")
    log.info("Written %d item(s) to %s (%.1f KB).", len(files), output_path, output_path.stat().st_size / 1024)


def main():
    log.info("=== VOD Playlist Generator started ===")

    if not API_KEY:
        log.error("GDRIVE_API_KEY not set.")
        sys.exit(1)
    if not FOLDER_ID:
        log.error("GDRIVE_FOLDER_ID not set.")
        sys.exit(1)

    log.info("Listing files in folder: %s", FOLDER_ID)
    files = list_files(FOLDER_ID, API_KEY)
    log.info("Found %d video file(s).", len(files))

    if not files:
        log.warning("No video files found. Playlist will be empty.")

    generate_m3u(files, OUTPUT_FILE, GROUP_LABEL, API_KEY)
    log.info("=== Done! ===")


if __name__ == "__main__":
    main()
