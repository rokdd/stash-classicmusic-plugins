"""Marker scraper: the chapters stored in the scene's video file.

stdin: {"scene": {...}}  → stdout: a JSON list of markers.
Uses ffprobe (STASH_FFPROBE: Stash's own, else the one on the PATH)."""

import json
import os
import subprocess
import sys


def chapters(path, ffprobe):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_chapters", "-of", "json", path],
        capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"ffprobe failed on {path}")
    return json.loads(out.stdout or "{}").get("chapters") or []


def main():
    scene = json.load(sys.stdin).get("scene") or {}
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    ffprobe = os.environ.get("STASH_FFPROBE") or "ffprobe"
    markers = []
    for i, ch in enumerate(chapters(files[0]["path"], ffprobe), 1):
        title = ((ch.get("tags") or {}).get("title") or "").strip()
        markers.append({
            "seconds": float(ch.get("start_time") or 0),
            "end_seconds": float(ch["end_time"]) if ch.get("end_time") else None,
            "title": title or f"Chapter {i}",
        })
    print(json.dumps(markers))


if __name__ == "__main__":
    main()
