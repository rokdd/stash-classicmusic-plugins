"""Marker scraper: markers from plain text.

stdin: {"scene": {...}, "text": "..."}  → stdout: a JSON list of markers.

Every line with a time in it becomes a marker; the rest of the line is its
title. Lines without a time are skipped. Understood:
  0:00 I. Allegro con brio          12:34 - 15:02 Andante
  1:02:03.5 Finale                  Scherzo (5:10)
  [00:07:41] Menuetto               3m20s Trio        95s Coda
A range (start - end) gives the marker its end; otherwise it ends where
the next one starts, and the last one at the end of the video. Separators
around the title (- – — | : . brackets, track numbers like "1." stay) are
trimmed.

A CUE sheet (TRACK / TITLE / PERFORMER / INDEX 01 mm:ss:ff) is read
track by track; PERFORMER becomes a tag."""

import json
import re
import sys

CLOCK = r"(?:(\d{1,2}):)?(\d{1,3}):(\d{2})(?:[.,](\d{1,3}))?"
UNITS = r"(?:(\d+)h\s*)?(?:(\d+)m(?:in)?\s*)?(\d+)s\b|(?:(\d+)h\s*)?(\d+)m(?:in)?\b"
TIME_RE = re.compile(rf"(?<![\d:]){CLOCK}(?![\d:])|(?<![\w]){UNITS}", re.I)
RANGE_SEP = re.compile(r"^\s*(?:-|–|—|to|bis)\s*$", re.I)
TRIM = " \t-–—|:;,.·•*>)]}([{<\"'"


def to_seconds(m):
    h, mi, s, frac, uh, um, us, uh2, um2 = m.groups()
    if mi is not None:
        return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (float("0." + frac) if frac else 0)
    if us is not None:
        return int(uh or 0) * 3600 + int(um or 0) * 60 + int(us)
    return int(uh2 or 0) * 3600 + int(um2) * 60


def parse_lines(text):
    markers = []
    for line in text.splitlines():
        times = list(TIME_RE.finditer(line))
        if not times:
            continue
        start = to_seconds(times[0])
        end = None
        spans = [times[0].span()]
        # "a - b": a range, when only a separator is between the two times.
        if len(times) > 1 and RANGE_SEP.match(line[times[0].end():times[1].start()]):
            end = to_seconds(times[1])
            spans = [(times[0].start(), times[1].end())]
        title = line
        for a, b in reversed(spans):
            title = title[:a] + " " + title[b:]
        title = re.sub(r"[\[(]\s*[\])]", " ", title)  # brackets the time was in
        title = re.sub(r"\s+", " ", title).strip(TRIM).strip()
        markers.append({"seconds": start, "end_seconds": end, "title": title})
    return markers


def parse_cue(text):
    markers, current, performer = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        word, _, rest = line.partition(" ")
        value = rest.strip().strip('"')
        word = word.upper()
        if word == "TRACK":
            current = {"title": "", "tags": []}
            markers.append(current)
        elif current is None:
            continue
        elif word == "TITLE":
            current["title"] = value
        elif word == "PERFORMER" and value:
            current["tags"] = [value]
        elif word == "INDEX" and value.startswith("01 "):
            mm, ss, ff = (int(x) for x in value[3:].strip().split(":"))
            current["seconds"] = mm * 60 + ss + ff / 75
    return [m for m in markers if "seconds" in m]


def fill_ends(markers, duration):
    """Sorted by start; a marker without an end ends where the next starts
    (the last at the end of the video); untitled ones get "Chapter n"."""
    markers.sort(key=lambda m: m["seconds"])
    for i, m in enumerate(markers):
        if m.get("end_seconds") is None:
            nxt = markers[i + 1]["seconds"] if i + 1 < len(markers) else (duration or None)
            m["end_seconds"] = nxt if nxt and nxt > m["seconds"] else None
        if not m.get("title"):
            m["title"] = f"Chapter {i + 1}"
    return markers


def main():
    payload = json.load(sys.stdin)
    text = payload.get("text") or ""
    scene = payload.get("scene") or {}
    is_cue = re.search(r"^\s*INDEX\s+01\s", text, re.M | re.I)
    markers = parse_cue(text) if is_cue else parse_lines(text)
    duration = max([f.get("duration") or 0 for f in scene.get("files") or []] or [0])
    print(json.dumps(fill_ends(markers, duration)))


if __name__ == "__main__":
    main()
