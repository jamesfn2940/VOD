#!/usr/bin/env python3
"""
Google Drive VOD Playlist Generator
Uses Service Account for Shared Drive access.
"""

import json
import os
import sys
import logging
import urllib.request
import urllib.parse
import time
import hmac
import hashlib
import base64
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_SERVICE_ACCOUNT", "")
FOLDER_ID   = os.environ.get("GDRIVE_FOLDER_ID", "")
OUTPUT_FILE = Path(os.environ.get("VOD_OUTPUT_FILE", "vod_playlist.m3u"))
ROOT_GROUP  = os.environ.get("VOD_GROUP", "VOD")
VIDEO_EXTS  = {".mp4", ".mkv", ".avi", ".mov", ".ts", ".m4v"}


def get_access_token(sa_json):
    """Get OAuth2 access token from Service Account JSON using JWT."""
    try:
        sa = json.loads(sa_json)
    except Exception as e:
        log.error("Failed to parse service account JSON: %s", e)
        sys.exit(1)

    # Build JWT
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

    # Sign with RSA private key using only stdlib
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend

        private_key = serialization.load_pem_private_key(
            sa["private_key"].encode(),
            password=None,
            backend=default_backend()
        )
        message = f"{header}.{payload}".encode()
        signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        sig = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    except ImportError:
        log.error("cryptography library not available. Installing...")
        os.system("pip install cryptography --break-system-packages -q")
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend

        private_key = serialization.load_pem_private_key(
            sa["private_key"].encode(),
            password=None,
            backend=default_backend()
        )
        message = f"{header}.{payload}".encode()
        signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        sig = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    jwt_token = f"{header}.{payload}.{sig}"

    # Exchange JWT for access token
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
        result = json.loads(resp.read())

    return result["access_token"]


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
        log.error("API error for folder %s: %s", folder_id, e)
        return {"files": []}


def list_recursive(folder_id, group_name, token):
    results = []
    page_token = None

    while True:
        data = api_list(folder_id, token, page_token)
        for f in data.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                sub_group = f"{group_name} - {f['name']}" if group_name else f["name"]
                log.info("  Entering subfolder: %s", f["name"])
                results.extend(list_recursive(f["id"], sub_group, token))
            else:
                ext = Path(f["name"]).suffix.lower()
                if ext in VIDEO_EXTS:
                    results.append({"id": f["id"], "name": f["name"], "group": group_name})

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return results


def make_stream_url(file_id):
    return f"https://drive.google.com/uc?export=download&id={file_id}"


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

    if not SERVICE_ACCOUNT_JSON:
        log.error("GDRIVE_SERVICE_ACCOUNT not set.")
        sys.exit(1)
    if not FOLDER_ID:
        log.error("GDRIVE_FOLDER_ID not set.")
        sys.exit(1)

    log.info("Getting access token...")
    token = get_access_token(SERVICE_ACCOUNT_JSON)
    log.info("Access token obtained.")

    log.info("Scanning folder recursively: %s", FOLDER_ID)
    files = list_recursive(FOLDER_ID, ROOT_GROUP, token)
    log.info("Found %d video file(s) total.", len(files))

    if not files:
        log.warning("No video files found.")

    generate_m3u(files, OUTPUT_FILE)
    log.info("=== Done! ===")


if __name__ == "__main__":
    main()
