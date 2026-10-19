"""Marker scraper: the scene split where the picture goes black.

stdin: {"scene": {...}}  → stdout: {"markers": [...], "notes": "..."}.
Uses ffmpeg (STASH_FFMPEG, else the one on the PATH): blackdetect on a small,
5-frames-a-second copy of the picture, the whole video once. The stretches
found are remembered per file (by path, size and time changed), so scraping
again is instant.

A marker starts where the picture comes back after a black stretch and ends
where the next black begins; the video's start counts as the first start.
Black stretches at the very start or end of the video are the video's own
fade-in and fade-out and give no marker. Settings in the environment:
BLACK_MIN (shortest black in seconds, default 1.0)."""

import hashlib
import inspect
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import storage  # noqa: E402 — where the readings are kept

FPS = 5
DETECT_MIN = 0.3  # seconds: everything this long is read and kept; BLACK_MIN picks from it
MAX_MARKERS = 200
CACHE_KEEP = 200  # files


def detect(path, ffmpeg):
    """[(start, end)] of every black stretch of at least DETECT_MIN seconds."""
    proc = subprocess.run(
        [ffmpeg, "-nostats", "-v", "info", "-skip_frame", "noref", "-i", path, "-map", "0:v:0", "-an", "-sn", "-dn",
         "-vf", f"fps={FPS},scale=160:-2,blackdetect=d={DETECT_MIN}:pic_th=0.98:pix_th=0.10",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg couldn't read the picture: {proc.stderr.strip()[-400:]}")
    found = []
    for m in re.finditer(r"black_start:([\d.]+)\s+black_end:([\d.]+)", proc.stderr):
        found.append((float(m.group(1)), float(m.group(2))))
    return found


def cached_detect(path, ffmpeg):
    st = os.stat(path)
    logic = hashlib.sha1(inspect.getsource(detect).encode()).hexdigest()[:12]
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{FPS}|{DETECT_MIN}|{logic}".encode()).hexdigest()
    cache_dir = storage.folder("frames")
    cache = os.path.join(cache_dir, "black-" + key + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            return [tuple(x) for x in json.load(f)]
    except (OSError, ValueError):
        pass
    found = detect(path, ffmpeg)
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump([[round(a, 2), round(b, 2)] for a, b in found], f)
        old = sorted((os.path.join(cache_dir, n) for n in os.listdir(cache_dir) if n.startswith("black-")),
                     key=os.path.getmtime)
        for stale in old[:-CACHE_KEEP]:
            os.remove(stale)
    except OSError:
        pass  # no cache then
    return found


def markers_for(blacks, end_of_video, min_black):
    """(markers, notes) from the black stretches [(start, end)]."""
    blacks = sorted(b for b in blacks if b[1] - b[0] >= min_black)
    # the video's own fade-in / fade-out
    first = 0.0
    if blacks and blacks[0][0] <= 1.0:
        first = blacks.pop(0)[1]
    if blacks and end_of_video and blacks[-1][1] >= end_of_video - 1.0:
        end_of_video = blacks.pop()[0]
    if len(blacks) > MAX_MARKERS - 1:
        blacks = sorted(sorted(blacks, key=lambda b: b[1] - b[0], reverse=True)[:MAX_MARKERS - 1])
    starts = [first] + [b[1] for b in blacks]
    ends = [b[0] for b in blacks] + [end_of_video or None]
    markers = []
    for i, (s, e) in enumerate(zip(starts, ends)):
        markers.append({"seconds": round(s, 1), "end_seconds": round(e, 1) if e and e > s else None, "title": f"Part {i + 1}"})
    n = len(blacks)
    return markers, f"{n} black stretch{'' if n == 1 else 'es'} of {min_black:g} s or more found."


def main():
    scene = json.load(sys.stdin).get("scene") or {}
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    path = files[0]["path"]
    if not os.path.isfile(path):
        raise SystemExit(f"Can't find the file: {path}")
    try:
        min_black = max(DETECT_MIN, float(os.environ.get("BLACK_MIN") or 1.0))
    except ValueError:
        min_black = 1.0
    blacks = cached_detect(path, os.environ.get("STASH_FFMPEG") or "ffmpeg")
    markers, notes = markers_for(blacks, files[0].get("duration") or 0, min_black)
    if len(markers) < 2:
        shorter = [b for b in blacks if b[1] - b[0] >= DETECT_MIN]
        notes = (f"No black frames of {min_black:g} s or more" + (f" ({len(shorter)} shorter ones were found — "
                 "lower \"Shortest black\" in the plugin's settings)" if shorter else "") + " — nothing to split at.")
        markers = []
    print(json.dumps({"markers": markers, "notes": notes}))


if __name__ == "__main__":
    main()
