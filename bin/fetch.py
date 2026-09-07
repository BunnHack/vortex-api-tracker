#!/usr/bin/env python3
"""Fetch the Vortex Studio Windows installer and extract the embedded binary.

Uses the same auth wall as the Studio download: /download/studio-windows only
returns the zip when logged in, so we first POST credentials to /login to get a
session cookie, then pull the installer.

The latest air-platform version is read from the public
GET /api/studio-version endpoint and written to version.txt, so the analyzer
tags snapshots with the real reported engine version (no login required).

Environment:
    VORTEX_USER      playvortex.io username (or email)
    VORTEX_PASSWORD  playvortex.io password

Outputs:
    studio.zip     (zip) raw installer archive
    studio.exe     (pe)  extracted VortexStudio.exe
    version.txt    (str) reported air-platform version from /api/studio-version
"""
import json
import os
import sys
import zipfile

import requests

BASE = "https://playvortex.io"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def fail(msg):
    print(f"[fetch] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def login(session):
    user = os.getenv("VORTEX_USER")
    password = os.getenv("VORTEX_PASSWORD")
    if not user or not password:
        fail("set VORTEX_USER and VORTEX_PASSWORD env vars")
    r = session.post(
        f"{BASE}/login",
        data={"username": user, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if r.status_code != 200:
        fail(f"login HTTP {r.status_code}: {r.text[:200]}")
    try:
        body = r.json()
    except Exception:
        body = r.text[:80]
    if not (isinstance(body, dict) and body.get("ok")):
        fail(f"login rejected: {body}")
    me = session.get(f"{BASE}/me")
    print(f"[fetch] logged in as {me.text[:120]}", file=sys.stderr)
    return


def download(session, path, dest):
    r = session.get(f"{BASE}{path}", stream=True, headers={"User-Agent": UA})
    if r.status_code != 200:
        fail(f"{path} -> HTTP {r.status_code} ({r.text[:120]})")
    with open(dest, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    print(f"[fetch] saved {dest} ({os.path.getsize(dest):,} bytes)", file=sys.stderr)
    return dest


def extract(exe_path, zip_path):
    # re-invent the archive layout: VortexStudio/VortexStudio.exe
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.filename.lower().endswith(".exe"):
                with z.open(info) as src, open(exe_path, "wb") as dst:
                    dst.write(src.read())
                print(f"[fetch] extracted {info.filename} -> {exe_path}", file=sys.stderr)
                return
    fail("no .exe found in studio zip")


def fetch_version(session):
    """Reported engine/air-platform version from the public studio-version API."""
    try:
        r = session.get(f"{BASE}/api/studio-version", timeout=20)
        r.raise_for_status()
        return r.json().get("version", "")
    except Exception as e:
        print(f"[fetch] version fetch failed ({e}); leaving version.txt absent",
              file=sys.stderr)
        return ""


def main():
    os.makedirs(ROOT, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA
    # prime session with the landing page (sets Cloudflare cookies)
    session.get(f"{BASE}/")
    login(session)

    version = fetch_version(session)
    if version:
        with open(os.path.join(ROOT, "version.txt"), "w") as f:
            f.write(version + "\n")
        print(f"[fetch] air-platform version {version} -> version.txt", file=sys.stderr)

    zip_path = os.path.join(ROOT, "studio.zip")
    exe_path = os.path.join(ROOT, "studio.exe")
    download(session, "/download/studio-windows", zip_path)
    extract(exe_path, zip_path)

    # strip a directory prefix so the PE sits at repo root for analysis
    pe = "studio.exe"
    if not os.path.exists(os.path.join(ROOT, pe)):
        fail(f"expected {pe} at {ROOT}")


if __name__ == "__main__":
    main()