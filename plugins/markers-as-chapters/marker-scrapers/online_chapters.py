"""Marker scraper: a video's chapters online, read with yt-dlp.

stdin: {"scene": {...}, "url": optional}  → stdout: a JSON list of markers.
Without "url" it tries the scene's URLs in turn and takes the first one
with chapters. yt-dlp: STASH_YTDLP, else the one on the PATH;
it impersonates Chrome when yt-dlp can (curl_cffi)."""

import json
import os
import subprocess
import sys


def impersonate_args(ytdlp):
    """["--impersonate", "chrome"] when this yt-dlp can do it (curl_cffi is
    installed), else []. Some sites turn plain yt-dlp requests away."""
    try:
        out = subprocess.run([ytdlp, "--list-impersonate-targets"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    for line in ((out.stdout or "") + (out.stderr or "")).splitlines():
        if line.strip().lower().startswith("chrome") and "unavailable" not in line.lower():
            return ["--impersonate", "chrome"]
    return []


def chapters(url, ytdlp):
    out = subprocess.run(
        [ytdlp, *impersonate_args(ytdlp), "--dump-single-json", "--skip-download", "--no-playlist", "--no-warnings", url],
        capture_output=True, text=True, timeout=150,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-500:] or f"yt-dlp failed on {url}")
    return json.loads(out.stdout or "{}").get("chapters") or []


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    ytdlp = os.environ.get("STASH_YTDLP") or "yt-dlp"
    urls = [payload["url"]] if payload.get("url") else (scene.get("urls") or [])
    if not urls:
        raise SystemExit("The scene has no URL — enter one to scrape.")
    errors = []
    for url in urls:
        try:
            found = chapters(url, ytdlp)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url}: {exc}")
            continue
        if found:
            print(json.dumps([
                {"seconds": float(c.get("start_time") or 0),
                 "end_seconds": float(c["end_time"]) if c.get("end_time") is not None else None,
                 "title": (c.get("title") or "").strip() or f"Chapter {i}"}
                for i, c in enumerate(found, 1)
            ]))
            return
    if errors and len(errors) == len(urls):
        raise SystemExit("\n".join(errors))
    print("[]")


if __name__ == "__main__":
    main()
