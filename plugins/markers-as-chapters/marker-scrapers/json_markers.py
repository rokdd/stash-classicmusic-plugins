"""Markers from JSON.

parse_json(text) → (markers, description) or None when the text isn't
JSON with markers in it.

Read:
  - Markers as Chapters' own export:
      {"version": 1, "title": …, "file": …, "markers": [{"seconds", "end_seconds",
       "title", "primary_tag", "tags"}, …]}
  - a plain list of such objects;
  - chapter lists of other tools — ffprobe -show_chapters -of json
    ({"chapters": [{"start_time", "end_time", "tags": {"title"}}]}, or "start" /
    "end" with "time_base"), yt-dlp's info file ({"chapters": [{"start_time",
    "end_time", "title"}]}), Stash's own markers ({"scene_markers": [{"seconds",
    "title", "primary_tag": {"name"}, "tags": [{"name"}]}]});
  - medici.tv ({"chapters": [{"tc_start", "tc_end", "multiline_name":
    "Composer\nWork\nMovement", "work": {"composers": […]}}]});
  - and in general any list of objects with a start (seconds, start,
    start_time, startTime, time, offset, timecode) and a title (title,
    name, label). Times are numbers of seconds or text like "1:02:03.5".
"""

import json
import re

LISTS = ("markers", "chapters", "scene_markers", "segments", "items", "tracks")
STARTS = ("seconds", "start_seconds", "start_time", "startTime", "tc_start", "start", "time", "offset", "timecode", "begin")
ENDS = ("end_seconds", "end_time", "endTime", "tc_end", "end", "stop")
TITLES = ("title", "name", "label", "text")


def _time(value, time_base=None):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) * time_base if time_base else float(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return float(text) * time_base if time_base else float(text)
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,3}):(\d{2})(?:[.,](\d+))?", text)
    if m:
        h, mi, s, frac = m.groups()
        return int(h or 0) * 3600 + int(mi) * 60 + int(s) + (float("0." + frac) if frac else 0)
    return None


def _name(value):
    if isinstance(value, dict):
        return str(value.get("name") or value.get("title") or "").strip()
    return str(value or "").strip()


def _base(item):
    """ffprobe's "start"/"end" are in time_base units ("1/1000")."""
    tb = item.get("time_base")
    if isinstance(tb, str) and "/" in tb and "start_time" not in item:
        a, b = tb.split("/", 1)
        try:
            return float(a) / float(b)
        except (ValueError, ZeroDivisionError):
            return None
    return None


def _marker(item):
    if not isinstance(item, dict):
        return None
    base = _base(item)
    start = next((_time(item[k], base if k in ("start",) else None) for k in STARTS if k in item and item[k] is not None), None)
    if start is None:
        return None
    end = next((_time(item[k], base if k in ("end",) else None) for k in ENDS if k in item and item[k] is not None), None)
    title = next((_name(item[k]) for k in TITLES if isinstance(item.get(k), (str, dict)) and _name(item[k])), "")
    work = item.get("work") if isinstance(item.get("work"), dict) else {}
    composers = [c for c in (work.get("composers") or item.get("composers") or []) if isinstance(c, str) and c.strip()]
    # medici.tv: "multiline_name" is "Composer\nWork\nMovement" — the whole
    # piece; the composers come as tags.
    if isinstance(item.get("multiline_name"), str) and item["multiline_name"].strip():
        lines = [x.strip() for x in item["multiline_name"].splitlines() if x.strip()]
        title = " – ".join(lines)
    if not title and isinstance(item.get("tags"), dict):  # ffprobe: tags.title
        title = _name(item["tags"].get("title"))
    tags = item.get("tags")
    tags = [_name(t) for t in tags if _name(t)] if isinstance(tags, list) else []
    tags += [c for c in composers if c not in tags]
    return {
        "seconds": start,
        "end_seconds": end if end is not None and end > start else None,
        "title": title,
        "primary_tag": _name(item.get("primary_tag")),
        "tags": tags,
    }


def _find_list(data):
    if isinstance(data, list):
        return data, "a list"
    if isinstance(data, dict):
        for key in LISTS:
            if isinstance(data.get(key), list):
                return data[key], f'its "{key}"'
        # one level down, e.g. {"data": {"findScene": {"scene_markers": […]}}}
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = _find_list(value)
                if found:
                    return found
    return None


def parse_json(text):
    stripped = (text or "").strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        data = json.loads(stripped)
    except ValueError:
        return None
    found = _find_list(data)
    if not found:
        return None
    items, where = found
    markers = [m for m in (_marker(i) for i in items) if m]
    if not markers:
        return None
    markers.sort(key=lambda m: m["seconds"])
    return markers, f"Read as JSON ({where}: {len(markers)} marker{'' if len(markers) == 1 else 's'})."
