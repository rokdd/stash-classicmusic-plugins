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
  .markers.json, .chapters.json, .json
                              markers as JSON (see json_markers.py)
  .txt                        a tracklist (see plain_text.py)
e.g. "Concert.mp4" + "Concert.cue" or "Concert.mp4.chapters.txt".

A CUE sheet with several FILE entries (one per CD side, say) starts each
file's tracks at 0:00 again: the files' lengths are added up — they must
be beside the sheet (see cue_offsets)."""

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from encoding_fix import decode_bytes
from plain_text import parse_cue, parse_lines, fill_ends

ENDINGS = (".cue", ".chapters.txt", ".chapters", ".chapters.xml", ".xml",
           ".ffmetadata", ".ffmeta", ".info.json", ".markers.json", ".chapters.json", ".json", ".txt")


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
    if name.endswith(".json"):
        from json_markers import parse_json
        found = parse_json(text)
        return found[0] if found else []
    if name.endswith(".xml"):
        return parse_matroska(text)
    if text.lstrip().startswith(";FFMETADATA") or name.endswith((".ffmetadata", ".ffmeta")):
        return parse_ffmetadata(text)
    if re.search(r"^\s*CHAPTER\d+\s*=", text, re.M | re.I):
        return parse_ogm(text)
    return parse_lines(text)


def _audio_length(path):
    ffprobe = os.environ.get("STASH_FFPROBE") or "ffprobe"
    out = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=120,
    )
    return float(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None


def _find_beside(cue_path, name):
    folder = os.path.dirname(cue_path)
    for candidate in (name, os.path.basename(name.replace("\\", "/"))):
        path = os.path.join(folder, candidate)
        if candidate and os.path.isfile(path):
            return path
    return None


def cue_offsets(cue_path, markers):
    """A CUE sheet with several FILE entries starts each file's tracks at
    0:00 again. The files' lengths (found beside the sheet, read with
    ffprobe) are added up, so every track gets its time in the whole
    recording. Returns a note when that can't be done."""
    numbers = {m.get("file") for m in markers if m.get("file") is not None}
    if len(numbers) <= 1:
        return ""
    # every FILE entry, in order — also ones without tracks of their own
    with open(cue_path, "rb") as f:
        text = decode_bytes(f.read())
    names = []
    for line in text.splitlines():
        word, _, rest = line.strip().partition(" ")
        if word.upper() == "FILE":
            m = re.match(r'\s*(?:"([^"]*)"|(\S+))', rest)
            names.append((m.group(1) if m.group(1) is not None else m.group(2)) if m else "")
    lengths, missing = [], []
    for name in names:
        path = _find_beside(cue_path, name)
        length = None
        if path:
            try:
                length = _audio_length(path)
            except (OSError, subprocess.SubprocessError, ValueError):
                length = None
        if length is None:
            missing.append(name or "?")
        lengths.append(length or 0)
    if missing:
        return (f"The CUE sheet has {len(names)} FILE entries, so its track starts begin again in every file and "
                f"aren't usable as they are. Put the audio files beside the sheet so their lengths can be added up "
                f"(not found or not readable: {', '.join(missing)}).")
    for m in markers:
        before = sum(lengths[:max(0, m.get("file", 1) - 1)])
        m["seconds"] = m["seconds"] + before
    return ""


def candidates(video):
    base, _ext = os.path.splitext(video)
    for stem in (base, video):
        for ending in ENDINGS:
            yield stem + ending


def read(path):
    with open(path, "rb") as f:
        return decode_bytes(f.read())


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
                notes = cue_offsets(path, markers) if any("file" in m for m in markers) else ""
                duration = max([x.get("duration") or 0 for x in files] or [0])
                print(json.dumps({"markers": fill_ends(markers, duration), "notes": notes}))
                return
    base = os.path.splitext(os.path.basename(files[0]["path"]))[0]
    raise SystemExit(
        f"No chapter file next to the video — e.g. {base}.cue, {base}.chapters.txt, "
        f"{base}.chapters.xml, {base}.ffmetadata, {base}.info.json or {base}.txt."
    )


if __name__ == "__main__":
    main()
