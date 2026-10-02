"""Marker scraper: the chapters stored in the scene's video file.

stdin: {"scene": {...}}  → stdout: {"markers": [...], "notes": …}.
Uses ffprobe (STASH_FFPROBE: Stash's own, else the one on the PATH).

Some files carry chapters without usable times: every chapter starts at 0
and ends at the end of the video (seen in MediathekView-style downloads),
plus junk entries ("nan" with no length, the file's own name, "Init"). Such
chapters are only a list of titles: the junk is dropped and the titles are
placed at the pauses in the audio (see pauses.py), like pasted titles."""

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


JUNK_TITLES = {"nan", "none", "null", "init"}


def without_times(markers):
    """True when the chapters can't be real: several, all starting together."""
    return len(markers) > 1 and len({round(m["seconds"], 3) for m in markers}) == 1


def main():
    scene = json.load(sys.stdin).get("scene") or {}
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    ffprobe = os.environ.get("STASH_FFPROBE") or "ffprobe"
    markers = []
    for i, ch in enumerate(chapters(files[0]["path"], ffprobe), 1):
        title = ((ch.get("tags") or {}).get("title") or "").strip()
        start = float(ch.get("start_time") or 0)
        end = float(ch["end_time"]) if ch.get("end_time") else None
        if end is not None and end <= start:
            continue  # a chapter with no length ("nan" at 0:00 – 0:00)
        markers.append({"seconds": start, "end_seconds": end, "title": title or f"Chapter {i}"})
    if not without_times(markers):
        print(json.dumps(markers))
        return
    name = os.path.basename(files[0]["path"])
    junk = {name.lower(), os.path.splitext(name)[0].lower()} | JUNK_TITLES
    titles = [m["title"] for m in markers if m["title"].lower() not in junk and not m["title"].startswith("Chapter ")]
    if not titles:
        print(json.dumps({"markers": [], "notes": "The file's chapters have no titles or times."}))
        return
    import pauses  # same folder
    placed, notes = pauses.scrape_titles(scene, titles)
    print(json.dumps({
        "markers": placed,
        "notes": f"The file's {len(markers)} chapters all start at the same time (no real times), so "
                 f"their titles were placed at the pauses in the audio. {notes}"}))


if __name__ == "__main__":
    main()
