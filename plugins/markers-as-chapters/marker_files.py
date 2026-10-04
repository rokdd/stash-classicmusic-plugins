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
import subprocess
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


# -- by the picture ------------------------------------------------------------------------------------------
#
# The frame at a marker in the file it was set on, looked for in the primary
# file: tiny grey pictures (64 × 36), each made comparable (its mean taken
# off, its contrast evened out), the one with the least difference wins.
# Two markers give the speed; then every marker is looked for itself,
# starting from the shift of the one before — so a shift that changes
# somewhere in between (a cut) is followed.

FRAME_W, FRAME_H = 64, 36
REACH = 300  # seconds searched around the first marker (an intro more or less)
CHAIN = 45  # seconds searched around where each marker should be (by the one before) …
POOR = 0.15  # … and further (REACH) when the best frames differ more than this (the same: under 0.08)
SEQUENCE = 8  # frames compared, every half second (4 seconds): movement tells still shots apart
MIN_APART = 60  # the second marker at least this far from the first


def grey_frames(path, start, length, fps):
    """[(time, normalised pixels)] from `start` for `length` seconds."""
    ffmpeg = os.environ.get("STASH_FFMPEG") or "ffmpeg"
    start = max(0.0, start)
    proc = subprocess.run([ffmpeg, "-v", "error", "-skip_frame", "noref", "-ss", f"{start:.3f}", "-i", path,
                           "-t", f"{length:.3f}", "-an", "-sn", "-vf",
                           f"fps={fps},scale={FRAME_W}:{FRAME_H},format=gray", "-f", "rawvideo", "-"],
                          capture_output=True)
    size = FRAME_W * FRAME_H
    data = proc.stdout
    return [(start + i / fps, normalise(data[i * size:(i + 1) * size])) for i in range(len(data) // size)]


def normalise(pixels):
    n = len(pixels)
    mean = sum(pixels) / n
    spread = (sum((p - mean) ** 2 for p in pixels) / n) ** 0.5 or 1.0
    return [(p - mean) / spread for p in pixels]


def difference(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def sequence(path, at):
    """The frames at `at`, every half second for SEQUENCE of them."""
    return [f for _, f in grey_frames(path, at, SEQUENCE * 0.5, 2)][:SEQUENCE]


def sequence_difference(seq, frames, i, step):
    """How far `seq` is from frames[i], frames[i + step], … (inf if they run out)."""
    total = 0.0
    for k, f in enumerate(seq):
        j = i + k * step
        if j >= len(frames):
            return float("inf")
        total += difference(f, frames[j][1])
    return total / len(seq)


def find_sequence(seq, path, centre, reach, speed=1.0):
    """(time in `path` where `seq` begins best within centre ± reach,
    difference): in half-second steps, then frame by frame (25 a second)."""
    span = SEQUENCE * 0.5 * speed
    coarse = grey_frames(path, centre - reach, 2 * reach + span, 2)
    if not coarse or not seq:
        return None, None
    step = max(1, round(speed))  # half-second frames: the sequence's step there
    best = min(range(len(coarse)), key=lambda i: sequence_difference(seq, coarse, i, step))
    t = coarse[best][0]
    fine = grey_frames(path, t - 0.6, 1.2 + span, 25)
    if not fine:
        return round(t, 2), round(sequence_difference(seq, coarse, best, step), 3)
    fine_step = round(0.5 * speed * 25)
    starts = [i for i, (ft, _) in enumerate(fine) if ft <= t + 0.6]
    i = min(starts, key=lambda i: sequence_difference(seq, fine, i, fine_step))
    return round(fine[i][0], 2), round(sequence_difference(seq, fine, i, fine_step), 3)


def by_picture(source, primary, markers):
    """(speed, offset, [(marker, new seconds, new end, difference)]) — every
    marker of `source` looked for in `primary` by the frames of its first
    seconds; starting where the one before suggests (so cuts in between
    are followed), further around when nothing fits there."""
    ordered = sorted(markers, key=lambda m: m["seconds"])
    found, shift = [], 0.0
    for n, m in enumerate(ordered):
        seq = sequence(source["path"], m["seconds"])
        new = diff = None
        if seq:
            reach = REACH if not any(d is not None and d <= POOR for _, _, d in found) else CHAIN
            new, diff = find_sequence(seq, primary["path"], m["seconds"] + shift, reach)
            if reach == CHAIN and (diff is None or diff > POOR):
                wide, wide_diff = find_sequence(seq, primary["path"], m["seconds"] + shift, REACH)
                if wide_diff is not None and (diff is None or wide_diff < diff):
                    new, diff = wide, wide_diff
        if new is not None and diff is not None and diff <= POOR:
            shift = new - m["seconds"]  # the next one starts from here
        found.append((m, new, diff))
    # the speed, from the markers found well: PAL / film, or the same
    good = [(m["seconds"], new) for m, new, d in found if new is not None and d is not None and d <= POOR]
    slopes = sorted((b2 - b1) / (a2 - a1) for (a1, b1), (a2, b2) in zip(good, good[1:]) if a2 - a1 >= 30)
    measured = slopes[len(slopes) // 2] if slopes else 1.0
    speed = min(SPEEDS, key=lambda s: abs(s - measured))
    if abs(speed - measured) > 0.01:
        speed = 1.0
    offset = (good[0][1] - good[0][0] * speed) if good else 0.0
    starts = {round(m["seconds"], 1): new for m, new, d in found if new is not None and d is not None and d <= POOR}
    placed = []
    for m, new, diff in found:
        if new is None:
            new = round(m["seconds"] * speed + offset, 2)
        own = new - m["seconds"] * speed
        end, new_end = m.get("end_seconds"), None
        if end is not None:
            # an end where another marker starts: there; else its own last
            # seconds looked for (a cut may lie in between)
            new_end = next((v for k, v in starts.items() if abs(k - end) <= 1), None)
            if new_end is None:
                seq = sequence(source["path"], max(0.0, end - SEQUENCE * 0.5))
                at, d = find_sequence(seq, primary["path"], end * speed + own - SEQUENCE * 0.5, CHAIN, speed) if seq else (None, None)
                new_end = round(at + SEQUENCE * 0.5 * speed, 2) if at is not None and d is not None and d <= POOR \
                    else round(end * speed + own, 2)
        placed.append((m, new, new_end, diff))
    return speed, offset, placed


def align(gql, scene_id, from_file, marker_ids=None, method="audio"):
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
    if method == "picture":
        return align_by_picture(scene, source, primary, marker_ids)
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


def align_by_picture(scene, source, primary, marker_ids):
    data = load()
    wanted = {str(i) for i in marker_ids} if marker_ids else None
    markers = [m for m in scene.get("scene_markers") or []
               if (str(m["id"]) in wanted if wanted is not None
                   else (data.get(str(m["id"])) or {}).get("file") == str(source["id"]))]
    if not markers:
        return {"markers": []}
    speed, offset, placed = by_picture(source, primary, markers)
    end_of = primary.get("duration") or float("inf")
    out = []
    for m, new, new_end, diff in placed:
        out.append({"id": m["id"], "title": m.get("title") or "", "seconds": m["seconds"], "end_seconds": m.get("end_seconds"),
                    "new_seconds": min(max(0.0, new), end_of), "new_end_seconds": min(new_end, end_of) if new_end is not None else None,
                    # alike: a difference of 0 is the same picture; 0.4 and more hardly alike
                    # alike: 0 the same pictures, from POOR on not alike
                    "likeness": round(max(0.0, 1 - diff / (2 * POOR)), 2) if diff is not None else 0.0,
                    "outside": new < 0 or new > end_of or diff is None or diff > POOR})
    likeness = sum(x["likeness"] for x in out) / len(out)
    return {"method": "picture", "speed": round(speed, 5), "offset": round(offset, 2), "likeness": round(likeness, 3),
            "from": {"id": source["id"], "basename": source["basename"], "duration": source.get("duration")},
            "to": {"id": primary["id"], "basename": primary["basename"], "duration": primary.get("duration")},
            "markers": out}
