"""The pauses between movements or works, in a scene's audio.

Used by Markers as Chapters for two things:
  - check(): the pauses, so the review dialog can show how every scraper's
    markers fit them (and shift or snap them onto them);
  - scrape_titles(): titles without times (the plain text scraper) placed
    at the pauses.
Run as a script it's still a scraper (not listed in the menu any more):
stdin: {"scene": {...}, "text": optional}
stdout: {"markers": [...], "notes": "what was found"}

Measures the loudness of the scene's audio every half second (ffmpeg's
astats; STASH_FFMPEG, else ffmpeg on the PATH) and looks for stretches
clearly quieter than the music around them — the threshold follows the
recording, so the audience's quiet between movements counts as a pause.
A marker starts where the music starts again, and ends where the next
pause begins.

With text — titles, one per line, in order — it looks for as many pieces
as there are titles: the longest pauses split the video, and the pieces
get the titles. If it finds too few pauses it tries again with shorter and
shallower ones. Without text, every pause gives a marker ("Part n").
The plain text scraper uses this too (scrape_titles), for a list of
titles without times."""

import hashlib
import json
import os
import re
import subprocess
import sys

WINDOW = 0.5  # seconds per loudness reading
# (shortest pause in seconds, how much quieter than the music in dB), tried in order
LEVELS = [(2.0, 25.0), (1.5, 20.0), (1.0, 15.0), (0.6, 12.0)]
MAX_UNNAMED = 60
# The check looks for shorter, shallower pauses too: a marker starting at
# one is a good sign even when it's a short breath between movements.
CHECK_LEVEL = (1.0, 15.0)
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".audio-cache")
CACHE_KEEP = 200  # files


def loudness(path, ffmpeg):
    """[(time, dB)] every WINDOW seconds of the first audio stream."""
    samples = int(8000 * WINDOW)
    proc = subprocess.run(
        [ffmpeg, "-nostats", "-v", "error", "-i", path, "-map", "0:a:0", "-vn", "-sn", "-dn",
         "-af", f"aformat=channel_layouts=mono,aresample=8000,asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
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


def cached_loudness(path, ffmpeg):
    """loudness(), remembered per file (by path, size and time changed), so
    scraping the same scene again doesn't read the audio again."""
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{WINDOW}".encode()).hexdigest()
    cache = os.path.join(CACHE_DIR, key + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            return [tuple(x) for x in json.load(f)]
    except (OSError, ValueError):
        pass
    levels = loudness(path, ffmpeg)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump([[round(t, 2), round(db, 1)] for t, db in levels], f)
        old = sorted((os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR)), key=os.path.getmtime)
        for stale in old[:-CACHE_KEEP]:
            os.remove(stale)
    except OSError:
        pass  # no cache then
    return levels


def scene_levels(scene):
    """(levels, end of video) for the scene's first file."""
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    path = files[0]["path"]
    if not os.path.isfile(path):
        raise SystemExit(f"Can't find the file: {path}")
    levels = cached_loudness(path, os.environ.get("STASH_FFMPEG") or "ffmpeg")
    if not levels:
        raise SystemExit("The file has no audio.")
    return levels, max(files[0].get("duration") or 0, levels[-1][0] + WINDOW)


def check(scene):
    """Where the music starts, ends and pauses — for the review dialog:
    {"music_start", "music_end", "pauses": [[start, end], ...]}."""
    levels, end = scene_levels(scene)
    min_pause, drop = CHECK_LEVEL
    threshold = threshold_for(levels, drop)
    loud = [t for t, db in levels if db >= threshold]
    pauses = [p for p in find_pauses(levels, min_pause, drop)
              if loud and p[0] > loud[0] and p[1] < loud[-1] + WINDOW]
    return {
        "music_start": round(loud[0], 1) if loud else 0.0,
        "music_end": round(loud[-1] + WINDOW, 1) if loud else round(end, 1),
        "pauses": [[round(a, 1), round(b, 1)] for a, b in pauses],
    }


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
    """(markers, notes)."""
    first_t = levels[0][0] if levels else 0.0
    best = None
    found = 0
    for min_pause, drop in LEVELS:
        pauses = find_pauses(levels, min_pause, drop)
        lead = pauses[0] if pauses and pauses[0][0] <= first_t + WINDOW else None
        trail = pauses[-1] if pauses and pauses[-1][1] >= end_of_video - WINDOW and pauses[-1] is not lead else None
        inner = [p for p in pauses if p is not lead and p is not trail]
        found = len(inner)
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
    if titles and len(markers) < len(titles):
        left = titles[len(markers):]
        notes = (f"Only {found} pause{'' if found == 1 else 's'} found for {len(titles)} titles, so "
                 f"{len(left)} title{'' if len(left) == 1 else 's'} got no marker: {'; '.join(left)}. "
                 "Check which pieces run together, or add times to those lines.")
    elif titles:
        notes = (f"{len(titles)} titles, {found} pause{'' if found == 1 else 's'} found"
                 + (f" — used the {len(titles) - 1} longest." if found > len(titles) - 1 else "."))
    else:
        notes = f"{found} pause{'' if found == 1 else 's'} found."
    return markers, notes


def scrape_titles(scene, titles):
    """Markers for the scene's audio split at its pauses, named by titles
    (or "Part n" without). Returns (markers, notes)."""
    levels, end = scene_levels(scene)
    return markers_for(levels, end, titles)


def main():
    payload = json.load(sys.stdin)
    markers, notes = scrape_titles(payload.get("scene") or {}, titles_from(payload.get("text")))
    print(json.dumps({"markers": markers, "notes": notes}))


if __name__ == "__main__":
    main()
