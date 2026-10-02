"""Marker scraper: markers from plain text.

stdin: {"scene": {...}, "text": "..."}  → stdout: {"markers": [...], "notes": …}.

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
track by track; PERFORMER becomes a tag.

JSON — Markers as Chapters' own export ("Copy as text…" → JSON), or the
chapter lists of ffprobe, yt-dlp and Stash (see json_markers.py) — is read
as it is, with primary tags and tags.

A table — columns split by tabs, ";", "|", several spaces or commas — is
read column by column (see table_text.py): start time or duration,
composer, title. Its markers are titled "Composer – Title", with the
composer as a tag.

Titles only — no line has a time: the lines are the pieces in order, and
they're placed at the pauses in the scene's audio (see pauses.py): the
video is split at the longest pauses into as many pieces as there are
lines."""

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


def _cue_time(value):
    mm, ss, ff = (int(x) for x in value.strip().split(":"))
    return mm * 60 + ss + ff / 75


def parse_cue(text):
    """Tracks of a CUE sheet. Each also gets "file" — which FILE entry it's
    in, counted from 1 (0: before any) — and that entry's "file_name": a
    sheet with several files starts every file's tracks at 0:00 again (see
    chapter_files.py, which adds up the files' lengths).

    Also read, in a track: REM PRIMARY_TAG "…", REM TAGS "a; b" (all tags —
    else PERFORMER is the tag) and REM END mm:ss:ff — what "Copy as text →
    CUE sheet" writes, so a sheet copied out comes back the same."""
    markers, current = [], None
    file_no, file_name = 0, ""
    for raw in text.splitlines():
        line = raw.strip()
        word, _, rest = line.partition(" ")
        value = rest.strip().strip('"')
        word = word.upper()
        if word == "FILE":
            m = re.match(r'\s*(?:"([^"]*)"|(\S+))', rest)
            file_no += 1
            file_name = (m.group(1) if m.group(1) is not None else m.group(2)) if m else ""
            continue
        if word == "TRACK":
            current = {"title": "", "tags": [], "file": file_no, "file_name": file_name}
            markers.append(current)
        elif word == "REM" and current is not None:
            key, _, rem = rest.strip().partition(" ")
            rem_value = rem.strip().strip('"')
            key = key.upper()
            if key == "PRIMARY_TAG":
                current["primary_tag"] = rem_value
            elif key == "TAGS":
                current["all_tags"] = [t.strip() for t in re.split(r"[;,]", rem_value) if t.strip()]
            elif key == "END":
                try:
                    current["end_seconds"] = _cue_time(rem_value)
                except ValueError:
                    pass
        elif current is None:
            continue
        elif word == "TITLE":
            current["title"] = value
        elif word == "PERFORMER" and value:
            current["tags"] = [value]
        elif word == "INDEX" and value.startswith("01 "):
            current["seconds"] = _cue_time(value[3:])
    for m in markers:
        if "all_tags" in m:
            m["tags"] = m.pop("all_tags")
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


def table_markers(rows, scene):
    """Markers from read_table's rows, or (titles, tags) when there are no
    times: ([markers], notes) / (None, (titles, tags))."""
    def title_of(r):
        composer, title = r.get("composer") or "", r.get("title") or ""
        return f"{composer} – {title}" if composer and title else (title or composer)

    def tags_of(r):
        return [r["composer"]] if r.get("composer") and r.get("title") else []

    if any(r.get("start") is not None for r in rows):
        markers = [{"seconds": r["start"], "end_seconds": r.get("end"), "title": title_of(r), "tags": tags_of(r)}
                   for r in rows if r.get("start") is not None]
        return markers, ""
    if any(r.get("duration") for r in rows):
        # Durations (a CD tracklist): each piece starts where the one before
        # ends, counted from 0:00.
        markers, t = [], 0.0
        for r in rows:
            d = r.get("duration") or 0
            markers.append({"seconds": t, "end_seconds": t + d if d else None, "title": title_of(r), "tags": tags_of(r)})
            t += d
        return markers, ("The times are durations, added up from 0:00 — if the music starts later, "
                         "shift all times (the Audio column suggests by how much).")
    return None, ([title_of(r) for r in rows], [tags_of(r) for r in rows])


def main():
    payload = json.load(sys.stdin)
    text = payload.get("text") or ""
    scene = payload.get("scene") or {}
    is_cue = re.search(r"^\s*INDEX\s+01\s", text, re.M | re.I)
    duration = max([f.get("duration") or 0 for f in scene.get("files") or []] or [0])

    if not is_cue:
        from json_markers import parse_json
        found = parse_json(text)
        if found:
            markers, how = found
            print(json.dumps({"markers": fill_ends(markers, duration), "notes": how}))
            return
        from table_text import read_table
        table = read_table(text)
        if table:
            rows, how = table
            markers, extra = table_markers(rows, scene)
            if markers is None:
                import pauses
                titles, tags = extra
                markers, notes = pauses.scrape_titles(scene, titles)
                for m, t in zip(markers, tags):
                    m["tags"] = t
                print(json.dumps({"markers": markers, "notes":
                    f"{how} No times, so the rows were placed at the pauses in the audio. {notes}",
                    "pieces": [{"title": t, "tags": g} for t, g in zip(titles, tags)]}))
                return
            print(json.dumps({"markers": fill_ends(markers, duration), "notes": f"{how} {extra}".strip()}))
            return

    markers = parse_cue(text) if is_cue else parse_lines(text)
    if not markers and not is_cue:
        import pauses  # titles without times: place them at the pauses
        titles = pauses.titles_from(text)
        if titles:
            markers, notes = pauses.scrape_titles(scene, titles)
            print(json.dumps({"markers": markers,
                              "notes": "No times in the text, so the lines were placed at the pauses in the audio. " + notes,
                              # all titles in order, so the dialog can place them again
                              # when a part is marked as not music
                              "pieces": [{"title": t, "tags": []} for t in titles]}))
            return
    print(json.dumps({"markers": fill_ends(markers, duration), "notes": ""}))


if __name__ == "__main__":
    main()
