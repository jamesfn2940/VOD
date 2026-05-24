#!/usr/bin/env python3
"""
Google Drive VOD Playlist Generator
Reads all video files recursively from a Google Drive folder and generates an M3U playlist.
Subfolders become group-title categories.
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

API_KEY     = os.environ.get("GDRIVE_API_KEY", "")
FOLDER_ID   = os.environ.get("GDRIVE_FOLDER_ID", "")
OUTPUT_FILE = Path(os.environ.get("VOD_OUTPUT_FILE", "vod_playlist.m3u"))
ROOT_GROUP  = os.environ.get("VOD_GROUP", "VOD")
VIDEO_EXTS  = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m4v"}


def api_list(folder_id, page_token=None):
    """Single page API call."""
    params = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "nextPageToken,files(id,name,mimeType)",
        "pageSize": "1000",
        "key": API_KEY,
    }
    if page_token:
        params["pageToken"] = page_token
    url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.error("API error for folder %s: %s", folder_id, e)
        return {"files": []}


def list_recursive(folder_id, group_name):
    """Recursively list all video files. Subfolders become group names."""
    results = []
    page_token = None

    while True:
        data = api_list(folder_id, page_token)
        for f in data.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                # Recurse into subfolder — subfolder name becomes group
                sub_group = f"{group_name} - {f['name']}" if group_name else f["name"]
                log.info("  Entering subfolder: %s", f["name"])
                results.extend(list_recursive(f["id"], sub_group))
            else:
                ext = Path(f["name"]).suffix.lower()
                if ext in VIDEO_EXTS:
                    results.append({"id": f["id"], "name": f["name"], "group": group_name})

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results


def make_stream_url(file_id):
    return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={API_KEY}"


def generate_m3u(files, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in sorted(files, key=lambda x: (x["group"], x["name"])):
            name  = Path(item["name"]).stem
            group = item["group"] or ROOT_GROUP
            url   = make_stream_url(item["id"])
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

    log.info("Scanning folder recursively: %s", FOLDER_ID)
    files = list_recursive(FOLDER_ID, ROOT_GROUP)
    log.info("Found %d video file(s) total.", len(files))

    if not files:
        log.warning("No video files found.")

    generate_m3u(files, OUTPUT_FILE)
    log.info("=== Done! ===")


if __name__ == "__main__":
    main()
