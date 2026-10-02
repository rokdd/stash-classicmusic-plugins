"""Marker scraper: the chapters stored in the scene's video file.

stdin: {"scene": {...}}  → stdout: {"markers": [...], "notes": "..."}.
Uses ffprobe (STASH_FFPROBE: Stash's own, else the one on the PATH).

Some files carry broken chapters: every one starting at 0:00, titles like
"nan", "Init" or the file's own name. Then:
  - titles that aren't chapter titles are left out;
  - for MP4 / M4V / MOV the QuickTime chapter track is read directly (see
    mp4_chapters.py) — it may still have the times ffprobe lost;
  - if there are no times anywhere, no markers are made; the notes list
    the chapter titles, for the plain text scraper (titles only are placed
    at the pauses in the audio)."""

import json
import os
import re
import subprocess
import sys

import mp4_chapters

JUNK = {"", "nan", "none", "null", "init", "untitled", "chapter"}


def ffprobe_chapters(path, ffprobe):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_chapters", "-of", "json", path],
        capture_output=True, timeout=120,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip() or f"ffprobe failed on {path}")
    chapters = json.loads(out.stdout.decode("utf-8", "replace") or "{}").get("chapters") or []
    return [(float(c.get("start_time") or 0),
             float(c["end_time"]) if c.get("end_time") else None,
             ((c.get("tags") or {}).get("title") or "").strip()) for c in chapters]


def is_junk(title, path):
    t = title.strip().lower()
    base = os.path.basename(path).lower()
    names = {base, os.path.splitext(base)[0]}
    # "Artist.Title.m4v" files: the part after the first dot too
    names |= {n.split(".", 1)[1] for n in list(names) if "." in n}
    return (t in JUNK or t in names or re.fullmatch(r"[\d\s.:-]*", t) is not None
            or re.search(r"\.(mp4|m4v|mkv|mov|avi|webm|ts|m2ts|wmv|flv|mpg|mpeg)$", t) is not None)


def distinct_starts(chapters):
    return len({round(c[0], 1) for c in chapters})


def main():
    scene = json.load(sys.stdin).get("scene") or {}
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    path = files[0]["path"]
    ffprobe = os.environ.get("STASH_FFPROBE") or "ffprobe"

    chapters = [c for c in ffprobe_chapters(path, ffprobe) if not is_junk(c[2], path)]
    notes = ""
    if len(chapters) > 1 and distinct_starts(chapters) == 1:
        # Broken: every chapter at the same time. The chapter track may
        # still know better.
        track = []
        if path.lower().endswith((".mp4", ".m4v", ".mov", ".m4a")):
            try:
                track = [(t, None, title) for t, title in mp4_chapters.read_chapters(path) if not is_junk(title, path)]
            except Exception:  # noqa: BLE001 — a file it can't read is just "no help"
                track = []
        if len(track) > 1 and distinct_starts(track) > 1:
            chapters = track
            notes = "The file's chapter list had no times; they were read from its chapter track instead."
        else:
            titles = list(dict.fromkeys(c[2] for c in (track or chapters)))
            print(json.dumps({"markers": [], "notes":
                f"The file's {len(titles)} chapters have no times — all start at 0:00 — so they can't become markers. "
                "Their titles: " + "; ".join(titles) + ". To place them at the pauses in the audio, paste the titles "
                "(ideally the whole programme, in concert order) into Plain text."}))
            return

    chapters.sort(key=lambda c: c[0])
    markers = []
    for i, (start, end, title) in enumerate(chapters):
        if end is None or end <= start:
            end = chapters[i + 1][0] if i + 1 < len(chapters) else None
        markers.append({"seconds": start, "end_seconds": end, "title": title or f"Chapter {i + 1}"})
    print(json.dumps({"markers": markers, "notes": notes}))


if __name__ == "__main__":
    main()
