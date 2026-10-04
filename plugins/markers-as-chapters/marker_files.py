"""Markers and the scene's files.

A marker's time belongs to the file it was set on. Stash doesn't keep which
one: when scenes are merged, the markers of all of them move to the one
scene with their times as they were; when the primary file changes, the
markers stay as they are. With files of different lengths (another cut, an
intro more or less, PAL speed-up) the markers are then off.

So:
  - record(): which file each marker was made on — by a hook when a marker
    is created or moved, and for all markers of scenes with one file by the
    task "Remember each marker's file" (best run once before merging);
    kept in .marker-files.json in the plugin's folder: {marker id: {"file":
    file id, "seconds": its time then}}.
  - files_of(): per scene, which markers were made on which file, and
    whether that's the primary one.
  - align(): the times on one file → on the primary, by comparing the two
    files' audio (the loudness every half second, as for the pause check):
    one offset (and a speed: 25 vs 23.976 fps) for the whole, then each
    marker looked at closer, in the two minutes around it — so a cut-out
    intro or a missing piece in between doesn't throw the rest off.
"""

import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, ".marker-files.json")
SAME_LENGTH = 1.5  # seconds: files this close in length are taken as the same recording
STEP = 0.5  # seconds per loudness reading (pauses.WINDOW)
MAX_SHIFT = 900  # seconds the two files may be apart at most (the first search)
SPEEDS = (1.0, 25 / 23.976, 23.976 / 25)  # the same, PAL speed-up, and back …
SPEED_MARGIN = 0.15  # … another speed only when it fits this much better …
SPEED_SURE = 0.9  # … and this well (a real speed-up fits almost perfectly)
LOCAL = 60  # seconds before and after a marker compared closer …
LOCAL_SHIFT = 30  # … allowed to differ this much from the whole's offset
_lock = threading.Lock()


# -- the record --------------------------------------------------------------------------------------

def load():
    try:
        with open(RECORD, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(data):
    tmp = RECORD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, RECORD)


def record(entries):
    """entries: {marker id: (file id, seconds)}."""
    with _lock:
        data = load()
        for marker_id, (file_id, seconds) in entries.items():
            data[str(marker_id)] = {"file": str(file_id), "seconds": seconds}
        save(data)


def forget(marker_ids):
    with _lock:
        data = load()
        for marker_id in marker_ids:
            data.pop(str(marker_id), None)
        save(data)


SCENE = """query($id: ID!) { findScene(id: $id) { id
  files { id basename path duration }
  scene_markers { id seconds end_seconds title primary_tag { name } } } }"""


def hook(gql, context):
    """SceneMarker.Create.Post / .Update.Post: the marker was set (or moved)
    on the scene's primary file — unless only its title or tags changed."""
    marker_id = context.get("id")
    data = context.get("input") or {}
    scene_id = data.get("scene_id")
    if context.get("type", "").startswith("SceneMarker.Destroy"):
        forget([marker_id])
        return
    if not marker_id or not scene_id:
        return
    scene = gql(SCENE, {"id": scene_id}).get("findScene") or {}
    files = scene.get("files") or []
    marker = next((m for m in scene.get("scene_markers") or [] if str(m["id"]) == str(marker_id)), None)
    if not files or not marker:
        return
    known = load().get(str(marker_id))
    if known and context.get("type", "").startswith("SceneMarker.Update") and abs(known["seconds"] - marker["seconds"]) < 0.01:
        return  # the time wasn't changed: still the file it was set on
    record({marker_id: (files[0]["id"], marker["seconds"])})


def remember_all(gql, log):
    """The task: for every scene with one file, its markers belong to it."""
    page, done = 1, 0
    data = load()
    while True:
        result = gql("""query($page: Int!) { findScenes(scene_filter: {has_markers: "true"}, filter: {per_page: 200, page: $page}) {
            count scenes { id files { id } scene_markers { id seconds } } } }""", {"page": page})["findScenes"]
        for scene in result["scenes"]:
            if len(scene["files"]) != 1:
                continue
            entries = {m["id"]: (scene["files"][0]["id"], m["seconds"]) for m in scene["scene_markers"]
                       if str(m["id"]) not in data}
            if entries:
                record(entries)
                done += len(entries)
        if page * 200 >= result["count"]:
            break
        page += 1
    log(f"Remembered the file of {done} markers (scenes with one file).")
    return {"remembered": done}


# -- per scene -------------------------------------------------------------------------------------------

def files_of(gql, scene_id):
    """{"files": [{id, basename, duration, primary, markers}], "markers": [{id,
    seconds, end_seconds, title, file (id or null), beyond_end}], "off": number
    of markers not (known to be) on the primary file}."""
    scene = gql(SCENE, {"id": scene_id}).get("findScene") or {}
    files = scene.get("files") or []
    if not files:
        return {"files": [], "markers": [], "off": 0}
    primary = files[0]
    data = load()
    # a single file: all its markers are on it
    if len(files) == 1:
        unknown = {m["id"]: (primary["id"], m["seconds"]) for m in scene.get("scene_markers") or [] if str(m["id"]) not in data}
        if unknown:
            record(unknown)
            data = load()
    by_id = {str(f["id"]): f for f in files}
    markers, off = [], 0
    for m in scene.get("scene_markers") or []:
        known = data.get(str(m["id"]))
        file_id = known["file"] if known and known["file"] in by_id else None
        beyond = m["seconds"] > (primary.get("duration") or 0) + 1
        on_other = file_id and file_id != str(primary["id"]) and \
            abs((by_id[file_id].get("duration") or 0) - (primary.get("duration") or 0)) > SAME_LENGTH
        if on_other or beyond:
            off += 1
        markers.append({"id": m["id"], "seconds": m["seconds"], "end_seconds": m.get("end_seconds"), "title": m.get("title") or "",
                        "primary_tag": (m.get("primary_tag") or {}).get("name"), "file": file_id, "beyond_end": beyond})
    counts = {}
    for m in markers:
        counts[m["file"]] = counts.get(m["file"], 0) + 1
    return {
        "files": [{"id": f["id"], "basename": f["basename"], "duration": f.get("duration"), "primary": i == 0,
                   "markers": counts.get(str(f["id"]), 0)} for i, f in enumerate(files)],
        "unknown": counts.get(None, 0),
        "markers": markers,
        "off": off,
    }


# -- aligning by the audio --------------------------------------------------------------------------------

def envelope(path):
    """The loudness every half second, made comparable: clipped to -60 dB
    and centred."""
    sys.path.insert(0, os.path.join(HERE, "marker-scrapers"))
    import pauses
    levels = [max(db, -60.0) for _t, db in pauses.cached_loudness(path, os.environ.get("STASH_FFMPEG") or "ffmpeg")]
    mean = sum(levels) / len(levels) if levels else 0
    return [v - mean for v in levels]


def shrink(values, n):
    return [sum(values[i:i + n]) / len(values[i:i + n]) for i in range(0, len(values), n)]


def stretch(values, speed):
    """The readings of a file played `speed` times as long."""
    if speed == 1.0:
        return values
    count = int(len(values) * speed)
    return [values[min(len(values) - 1, int(i / speed))] for i in range(count)]


def correlation(a, b, lag, lo=0, hi=None):
    """How alike a[i] and b[i + lag] are (−1 … 1), for i in lo … hi."""
    hi = len(a) if hi is None else hi
    start, end = max(lo, -lag), min(hi, len(b) - lag)
    if end - start < 20:
        return -1.0
    xs, ys = a[start:end], b[start + lag:end + lag]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sxx = syy = 0.0
    for x, y in zip(xs, ys):
        dx, dy = x - mx, y - my
        sxy += dx * dy
        sxx += dx * dx
        syy += dy * dy
    return sxy / ((sxx * syy) ** 0.5) if sxx and syy else -1.0


def whole(a, b):
    """(speed, offset in seconds, likeness) of file a's audio within b's:
    searched in 8-second steps, then 2, then half seconds around the best."""
    span = int(MAX_SHIFT / (STEP * 16))
    small_b = shrink(b, 16)
    per_speed = []
    for speed in SPEEDS:
        small_a = shrink(stretch(a, speed), 16)
        c, lag = max((correlation(small_a, small_b, lag), lag) for lag in range(-span, span + 1))
        per_speed.append((c, speed, lag * STEP * 16))
    # the same speed unless another fits clearly better (a cut makes any
    # speed look a little better)
    same = per_speed[0]
    other = max(per_speed[1:])
    likeness, speed, offset = other if other[0] >= SPEED_SURE and other[0] > same[0] + SPEED_MARGIN else same
    stretched = stretch(a, speed)
    for n in (4, 1):  # 2 s, then half seconds
        sa, sb = shrink(stretched, n), shrink(b, n)
        centre = int(round(offset / (STEP * n)))
        reach = 16 // n + 2
        likeness, lag = max((correlation(sa, sb, lag), lag) for lag in range(centre - reach, centre + reach + 1))
        offset = lag * STEP * n
    return speed, offset, likeness


def align(gql, scene_id, from_file, marker_ids=None):
    """Proposals: the markers made on `from_file` (or `marker_ids`) moved to
    where the same moment is in the primary file."""
    scene = gql(SCENE, {"id": scene_id}).get("findScene") or {}
    files = scene.get("files") or []
    source = next((f for f in files if str(f["id"]) == str(from_file)), None)
    if not source or not files:
        raise SystemExit("That file isn't the scene's any more.")
    primary = files[0]
    if str(source["id"]) == str(primary["id"]):
        raise SystemExit("That's the primary file already.")
    a, b = envelope(source["path"]), envelope(primary["path"])
    if not a or not b:
        raise SystemExit("One of the files has no audio to compare.")
    speed, offset, likeness = whole(a, b)
    stretched = stretch(a, speed)
    centre = int(round(offset / STEP))

    def place(seconds):
        """(where `seconds` of the source file is in the primary, likeness
        there): the two minutes around it compared, within LOCAL_SHIFT of
        the whole's offset; the whole's offset if they're not alike."""
        at = seconds * speed
        i = int(at / STEP)
        lo, hi = max(0, i - int(LOCAL / STEP)), min(len(stretched), i + int(LOCAL / STEP))
        found = max(((correlation(stretched, b, lag, lo, hi), lag)
                     for lag in range(centre - int(LOCAL_SHIFT / STEP), centre + int(LOCAL_SHIFT / STEP) + 1)),
                    default=(-1.0, centre))
        shift = found[1] * STEP if found[0] >= 0.6 else offset
        return round(at + shift, 2), round(found[0], 2)

    wanted = {str(i) for i in marker_ids} if marker_ids else None
    data = load()
    out = []
    for m in scene.get("scene_markers") or []:
        known = data.get(str(m["id"]))
        if wanted is not None and str(m["id"]) not in wanted:
            continue
        if wanted is None and not (known and known["file"] == str(source["id"])):
            continue
        new, local = place(m["seconds"])
        end = m.get("end_seconds")
        new_end = place(end)[0] if end is not None else None
        outside = new < 0 or new > (primary.get("duration") or float("inf"))
        new = min(max(0.0, new), primary.get("duration") or new)
        if new_end is not None:
            new_end = min(max(new, new_end), primary.get("duration") or new_end)
        out.append({"id": m["id"], "title": m.get("title") or "", "seconds": m["seconds"], "end_seconds": end,
                    "new_seconds": new, "new_end_seconds": new_end, "likeness": local,
                    "outside": outside})
    return {"speed": round(speed, 5), "offset": round(offset, 2), "likeness": round(likeness, 3),
            "from": {"id": source["id"], "basename": source["basename"], "duration": source.get("duration")},
            "to": {"id": primary["id"], "basename": primary["basename"], "duration": primary.get("duration")},
            "markers": out}
