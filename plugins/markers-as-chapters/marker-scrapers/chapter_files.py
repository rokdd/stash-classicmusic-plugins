"""Marker scraper: chapters from a file next to the scene's video.

stdin: {"scene": {...}}  → stdout: a JSON list of markers.

Looks next to each of the scene's files for one with the same name (with
or without the video's extension) and one of these endings, and uses the
first it finds:
  .cue                        CUE sheet (TRACK / TITLE / INDEX 01)
  .chapters.txt, .chapters    OGM (CHAPTER01=00:00:00.000 / CHAPTER01NAME=…)
                              or a tracklist (see plain_text.py)
  .chapters.xml, .xml         Matroska chapters (mkvmerge / mkvextract)
  .ffmetadata, .ffmeta        ffmpeg metadata ([CHAPTER] START / END / title)
  .info.json                  yt-dlp's info file ("chapters")
  .txt                        a tracklist (see plain_text.py)
e.g. "Concert.mp4" + "Concert.cue" or "Concert.mp4.chapters.txt"."""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from plain_text import parse_cue, parse_lines, fill_ends

ENDINGS = (".cue", ".chapters.txt", ".chapters", ".chapters.xml", ".xml",
           ".ffmetadata", ".ffmeta", ".info.json", ".txt")


def clock(text):
    """"01:02:03.500", "02:03", "01:02:03.123456789" → seconds."""
    parts = text.strip().split(":")
    return sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts)))


def parse_ogm(text):
    times, names = {}, {}
    for line in text.splitlines():
        m = re.match(r"\s*CHAPTER(\d+)(NAME)?\s*=\s*(.*)", line, re.I)
        if m:
            (names if m.group(2) else times)[m.group(1)] = m.group(3).strip()
    return [{"seconds": clock(t), "title": names.get(n, "")} for n, t in times.items()]


def parse_matroska(text):
    markers = []
    for atom in ET.fromstring(text).iter("ChapterAtom"):
        start = atom.findtext("ChapterTimeStart")
        end = atom.findtext("ChapterTimeEnd")
        if not start:
            continue
        markers.append({
            "seconds": clock(start),
            "end_seconds": clock(end) if end else None,
            "title": (atom.findtext("ChapterDisplay/ChapterString") or "").strip(),
        })
    return markers


def parse_ffmetadata(text):
    markers, current = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.upper() == "[CHAPTER]":
            current = {"timebase": 1 / 1000}
            markers.append(current)
        elif line.startswith("[") or current is None:
            current = None if line.startswith("[") else current
        elif "=" in line:
            key, value = line.split("=", 1)
            key = key.strip().upper()
            if key == "TIMEBASE":
                a, b = value.split("/")
                current["timebase"] = float(a) / float(b)
            elif key in ("START", "END"):
                current[key.lower()] = float(value)
            elif key == "TITLE":
                current["title"] = value.strip()
    return [{"seconds": m["start"] * m["timebase"],
             "end_seconds": m["end"] * m["timebase"] if "end" in m else None,
             "title": m.get("title", "")} for m in markers if "start" in m]


def parse_info_json(text):
    return [{"seconds": float(c.get("start_time") or 0),
             "end_seconds": c.get("end_time"),
             "title": c.get("title") or ""} for c in json.loads(text).get("chapters") or []]


def parse(path, text):
    name = path.lower()
    if name.endswith(".cue") or re.search(r"^\s*INDEX\s+01\s", text, re.M | re.I):
        return parse_cue(text)
    if name.endswith(".info.json"):
        return parse_info_json(text)
    if name.endswith(".xml"):
        return parse_matroska(text)
    if text.lstrip().startswith(";FFMETADATA") or name.endswith((".ffmetadata", ".ffmeta")):
        return parse_ffmetadata(text)
    if re.search(r"^\s*CHAPTER\d+\s*=", text, re.M | re.I):
        return parse_ogm(text)
    return parse_lines(text)


def file_length(path, ffprobe):
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=120)
        return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def join_cue_files(markers, cue_path):
    """A CUE sheet with several FILE lines: the INDEX times restart at 0:00
    in each file. Adds up the files' lengths (found next to the sheet, read
    with ffprobe) so every track gets its start in the joined recording.
    Returns a note — "" when nothing was wrong or everything was fixed."""
    numbers = sorted({m.get("file") or 0 for m in markers})
    if len(numbers) < 2:
        return ""
    folder = os.path.dirname(cue_path)
    ffprobe = os.environ.get("STASH_FFPROBE") or "ffprobe"
    offsets, total, missing = {}, 0.0, []
    for n in numbers:
        offsets[n] = total
        name = next(m["file_name"] for m in markers if (m.get("file") or 0) == n)
        found = next((p for p in (os.path.join(folder, name), os.path.join(folder, os.path.basename(name.replace("\\", "/"))))
                      if os.path.isfile(p)), None)
        length = file_length(found, ffprobe) if found else None
        if length is None:
            missing.append(name)
            total = None
            break
        total += length
    if missing:
        return (f"The CUE sheet has {len(numbers)} FILE entries (times restart at 0:00 in each) but "
                f"'{missing[0]}' couldn't be read next to it, so the starts are not usable — "
                "put the audio files beside the sheet, or use a sheet with one FILE.")
    for m in markers:
        m["seconds"] += offsets[m.get("file") or 0]
    return f"CUE sheet with {len(numbers)} FILE entries: the files' lengths were added up to place the tracks."


def candidates(video):
    base, _ext = os.path.splitext(video)
    for stem in (base, video):
        for ending in ENDINGS:
            yield stem + ending


def read(path):
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def main():
    scene = json.load(sys.stdin).get("scene") or {}
    files = scene.get("files") or []
    if not files:
        raise SystemExit("The scene has no file.")
    for f in files:
        for path in candidates(f["path"]):
            if not os.path.isfile(path):
                continue
            markers = parse(path, read(path))
            if markers:
                duration = max([x.get("duration") or 0 for x in files] or [0])
                note = join_cue_files(markers, path)
                print(json.dumps({"markers": fill_ends(markers, duration), "notes": note}))
                return
    base = os.path.splitext(os.path.basename(files[0]["path"]))[0]
    raise SystemExit(
        f"No chapter file next to the video — e.g. {base}.cue, {base}.chapters.txt, "
        f"{base}.chapters.xml, {base}.ffmetadata, {base}.info.json or {base}.txt."
    )


if __name__ == "__main__":
    main()
