"""Marker scraper: the pauses between movements or works.

stdin: {"scene": {...}, "text": optional}  → stdout: a JSON list of markers.

Measures the loudness of the scene's audio every half second (ffmpeg's
astats; STASH_FFMPEG, else ffmpeg on the PATH) and looks for stretches
clearly quieter than the music around them — the threshold follows the
recording, so the audience's quiet between movements counts as a pause.
A marker starts where the music starts again, and ends where the next
pause begins.

With text — titles, one per line, in order — it looks for as many pieces
as there are titles: the longest pauses split the video, and the pieces
get the titles. If it finds too few pauses it tries again with shorter and
shallower ones. Without text, every pause gives a marker ("Part n")."""

import json
import os
import re
import subprocess
import sys

WINDOW = 0.5  # seconds per loudness reading
# (shortest pause in seconds, how much quieter than the music in dB), tried in order
LEVELS = [(2.0, 25.0), (1.5, 20.0), (1.0, 15.0), (0.6, 12.0)]
MAX_UNNAMED = 60


def loudness(path, ffmpeg):
    """[(time, dB)] every WINDOW seconds of the first audio stream."""
    samples = int(8000 * WINDOW)
    proc = subprocess.run(
        [ffmpeg, "-nostats", "-v", "error", "-i", path, "-map", "0:a:0", "-vn", "-sn", "-dn",
         "-af", f"aresample=8000,asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
                "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg couldn't read the audio: {proc.stderr.strip()[-400:]}")
    levels, t = [], None
    for line in proc.stdout.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        if "RMS_level=" in line and t is not None:
            value = line.split("=", 1)[1].strip()
            try:
                db = float(value)
            except ValueError:
                db = -120.0
            levels.append((t, max(db, -120.0) if db == db else -120.0))  # NaN → silence
    return levels


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))] if ordered else -120.0


def threshold_for(levels, drop):
    music = percentile([db for _t, db in levels], 0.75)
    return min(music - drop, -30.0)


def find_pauses(levels, min_pause, drop):
    """[(start, end)] of quiet stretches at least min_pause long."""
    threshold = threshold_for(levels, drop)
    pauses, start = [], None
    for t, db in levels:
        if db < threshold:
            if start is None:
                start = t
        elif start is not None:
            if t - start >= min_pause:
                pauses.append((start, t))
            start = None
    if start is not None and levels and levels[-1][0] + WINDOW - start >= min_pause:
        pauses.append((start, levels[-1][0] + WINDOW))
    return pauses


def titles_from(text):
    titles = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*(\d{1,2}:)?\d{1,2}:\d{2}\s*", "", line).strip(" \t-–—|")
        if line:
            titles.append(line)
    return titles


def markers_for(levels, end_of_video, titles):
    first_t = levels[0][0] if levels else 0.0
    best = None
    for min_pause, drop in LEVELS:
        pauses = find_pauses(levels, min_pause, drop)
        lead = pauses[0] if pauses and pauses[0][0] <= first_t + WINDOW else None
        trail = pauses[-1] if pauses and pauses[-1][1] >= end_of_video - WINDOW and pauses[-1] is not lead else None
        inner = [p for p in pauses if p is not lead and p is not trail]
        wanted = len(titles) - 1 if titles else None
        if wanted is not None:
            if len(inner) < wanted and (min_pause, drop) != LEVELS[-1]:
                continue
            inner = sorted(sorted(inner, key=lambda p: p[1] - p[0], reverse=True)[:wanted])
        elif len(inner) > MAX_UNNAMED:
            inner = sorted(sorted(inner, key=lambda p: p[1] - p[0], reverse=True)[:MAX_UNNAMED])
        best = (lead, trail, inner)
        break
    lead, trail, inner = best
    # The music's first and last sound, however short the quiet around it.
    loud = [t for t, db in levels if db >= threshold_for(levels, drop)]
    music_start = loud[0] if loud else first_t
    music_end = loud[-1] + WINDOW if loud else end_of_video
    starts = [lead[1] if lead else music_start] + [p[1] for p in inner]
    ends = [p[0] for p in inner] + [trail[0] if trail else music_end]
    markers = []
    for i, (s, e) in enumerate(zip(starts, ends)):
        title = titles[i] if titles and i < len(titles) else f"Part {i + 1}"
        markers.append({"seconds": round(s, 1), "end_seconds": round(e, 1) if e > s else None, "title": title})
    return markers


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    path = files[0]["path"]
    if not os.path.isfile(path):
        raise SystemExit(f"Can't find the file: {path}")
    levels = loudness(path, os.environ.get("STASH_FFMPEG") or "ffmpeg")
    if not levels:
        raise SystemExit("The file has no audio.")
    end = max(files[0].get("duration") or 0, levels[-1][0] + WINDOW)
    print(json.dumps(markers_for(levels, end, titles_from(payload.get("text")))))


if __name__ == "__main__":
    main()
