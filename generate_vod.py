#!/usr/bin/env python3
"""
Google Drive VOD Playlist Generator via Vercel Proxy
Supports multiple folder IDs and TMDB thumbnail lookup.
"""

import json
import os
import sys
import logging
import urllib.request
import urllib.parse
import re
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_SERVICE_ACCOUNT", "")
FOLDER_IDS_RAW       = os.environ.get("GDRIVE_FOLDER_ID", "")
OUTPUT_FILE          = Path(os.environ.get("VOD_OUTPUT_FILE", "vod_playlist.m3u"))
ROOT_GROUP           = os.environ.get("VOD_GROUP", "VOD")
VERCEL_URL           = os.environ.get("VERCEL_URL", "https://googledrive-omega.vercel.app")
TMDB_API_KEY         = os.environ.get("TMDB_API_KEY", "")
VIDEO_EXTS           = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m4v"}
TMDB_IMAGE_BASE      = "https://image.tmdb.org/t/p/w500"


# ── TMDB ─────────────────────────────────────────────────────────────────────

def clean_title(filename):
    """Extract clean title and year from filename."""
    name = Path(filename).stem
    # Remove common release tags
    name = re.sub(r'\b(720p|1080p|2160p|4K|BluRay|WEB-DL|WEBRip|HDTV|x264|x265|HEVC|AAC|DTS|AC3)\b.*', '', name, flags=re.IGNORECASE)
    # Replace dots and underscores with spaces
    name = re.sub(r'[._]', ' ', name)
    # Extract year
    year_match = re.search(r'\b(19|20)\d{2}\b', name)
    year = year_match.group(0) if year_match else None
    # Remove year from title
    title = re.sub(r'\b(19|20)\d{2}\b', '', name).strip()
    title = re.sub(r'\s+', ' ', title).strip()
    return title, year


def tmdb_search(title, year=None, media_type="multi"):
    """Search TMDB for a title, return poster URL or empty string."""
    if not TMDB_API_KEY:
        return ""

    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": "en-US",
        "page": "1",
    }
    if year:
        params["year"] = year

    url = f"https://api.themoviedb.org/3/search/{media_type}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        results = data.get("results", [])
        if not results:
            return ""
        # Pick first result with a poster
        for result in results[:3]:
            poster = result.get("poster_path", "")
            if poster:
                return f"{TMDB_IMAGE_BASE}{poster}"
        return ""
    except Exception:
        return ""


def get_thumbnail(filename):
    """Get thumbnail URL for a video file."""
    if not TMDB_API_KEY:
        return ""
    title, year = clean_title(filename)
    if not title:
        return ""
    # Try multi search first, fallback to movie
    poster = tmdb_search(title, year, "multi")
    if not poster:
        poster = tmdb_search(title, year, "movie")
    if not poster:
        poster = tmdb_search(title, year, "tv")
    return poster


# ── Google Drive ──────────────────────────────────────────────────────────────

def get_access_token(sa_json):
    import time
    import base64

    sa = json.loads(sa_json)
    now = int(time.time())

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    payload = base64.urlsafe_b64encode(json.dumps({
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/drive.readonly",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }).encode()).rstrip(b"=").decode()

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend

    private_key = serialization.load_pem_private_key(
        sa["private_key"].encode(), password=None, backend=default_backend()
    )
    message = f"{header}.{payload}".encode()
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    sig = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    jwt_token = f"{header}.{payload}.{sig}"
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": jwt_token,
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


def api_list(folder_id, token, page_token=None):
    params = {
        "q": f"'{folder_id}' in parents and trashed=false",
        "fields": "nextPageToken,files(id,name,mimeType)",
        "pageSize": "1000",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if page_token:
        params["pageToken"] = page_token

    url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.error("API error: %s", e)
        return {"files": []}


def list_recursive(folder_id, group_name, token):
    results = []
    page_token = None

    while True:
        data = api_list(folder_id, token, page_token)
        for f in data.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                sub_group = f"{group_name} - {f['name']}" if group_name else f["name"]
                log.info("    Entering subfolder: %s", f["name"])
                results.extend(list_recursive(f["id"], sub_group, token))
            else:
                ext = Path(f["name"]).suffix.lower()
                if ext in VIDEO_EXTS:
                    results.append({
                        "id": f["id"],
                        "name": f["name"],
                        "group": group_name
                    })
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results


def make_stream_url(file_id):
    return f"{VERCEL_URL}/mp4/{file_id}.mp4"


def generate_m3u(files, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmdb_enabled = bool(TMDB_API_KEY)
    if tmdb_enabled:
        log.info("TMDB enabled — fetching thumbnails...")
    else:
        log.info("TMDB disabled — no thumbnails. Set TMDB_API_KEY to enable.")

    with output_path.open("w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for item in sorted(files, key=lambda x: (x["group"], x["name"])):
            name  = Path(item["name"]).stem
            group = item["group"] or ROOT_GROUP
            url   = make_stream_url(item["id"])
            logo  = get_thumbnail(item["name"]) if tmdb_enabled else ""
            if logo:
                log.info("  ✓ Thumbnail: %s", name)
            f.write(f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}\n')
            f.write(url + "\n")

    size_kb = output_path.stat().st_size / 1024
    log.info("Written %d item(s) to %s (%.1f KB).", len(files), output_path, size_kb)


def main():
    log.info("=== VOD Playlist Generator started ===")

    if not SERVICE_ACCOUNT_JSON:
        log.error("GDRIVE_SERVICE_ACCOUNT not set.")
        sys.exit(1)
    if not FOLDER_IDS_RAW:
        log.error("GDRIVE_FOLDER_ID not set.")
        sys.exit(1)

    log.info("Getting access token...")
    token = get_access_token(SERVICE_ACCOUNT_JSON)
    log.info("Access token obtained.")

    folder_ids = [f.strip() for f in FOLDER_IDS_RAW.split(",") if f.strip()]
    log.info("Processing %d folder(s)...", len(folder_ids))

    all_files = []
    for idx, folder_id in enumerate(folder_ids, 1):
        log.info("Scanning folder %d/%d: %s", idx, len(folder_ids), folder_id)
        files = list_recursive(folder_id, ROOT_GROUP, token)
        log.info("  Found %d file(s).", len(files))
        all_files.extend(files)

    log.info("Total: %d video file(s).", len(all_files))

    if not all_files:
        log.warning("No video files found.")

    generate_m3u(all_files, OUTPUT_FILE)
    log.info("=== Done! ===")


if __name__ == "__main__":
    main()
