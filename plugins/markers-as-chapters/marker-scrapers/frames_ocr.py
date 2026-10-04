"""Markers from text in the picture: captions ("Johann Strauss: Radetzky-
Marsch" in the lower third), title cards, burned-in subtitles.

How:
  1. One pass of ffmpeg over the video, one frame a second, scaled down,
     as edges (1-bit pictures).
  2. Text stays put for a few seconds and then goes: per cell of a 12 × 8
     grid, the edges that are in two frames running but not in most of the
     frames 10 and 20 seconds before and after are counted — a still stage
     or a logo is there all the time and drops out. A few cells with many
     more of them than the rest of the picture: something was written
     there (a still camera shot has them everywhere). Seconds running with
     the same cells are one text.
  3. Each such text is read once, from the full-size frame cut to those
     cells, with tesseract (OCR) — only those, not every frame.
  4. What was read becomes subtitle entries, and those markers like the
     Subtitles scraper makes them: a short text (a caption, a title card)
     gets a marker where it shows. Text that's there most of the time (a
     channel's logo) is left out.

Needs tesseract on the Stash server (Debian: apt install tesseract-ocr
tesseract-ocr-deu; Stash's Docker image: apk add tesseract-ocr
tesseract-ocr-data-deu) — the plugin setting "tesseract", else on the PATH.
The scan is remembered per file (in .frames-cache), so scraping the scene
again only reads the texts again.
"""

import difflib
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subtitles  # noqa: E402 — markers from the texts, like from subtitles

WIDTH = 480  # the scan's width in pixels
COLS, ROWS = 12, 8  # the grid
EDGES = "edgedetect=low=0.12:high=0.3"
MIN_SHARE = 0.04  # a cell with text: new standing edges in at least this share of it …
MIN_RISE = 3.0  # … and this many times more than the picture's median cell
MAX_HOT = 0.35  # more cells than this: a still camera shot, not text
MIN_CELLS = 3  # fewer: a speck
MAX_BOX = 0.5  # text over more of the picture than this: a still camera shot
MAX_READ = 1500  # texts read at most
LOGO_SHARE = 0.2  # text seen for more than this share of the video: a logo, left out
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".frames-cache")
CACHE_KEEP = 100
# How far it is, for the dialog: <plugin>/.progress/<scene id>.json
PROGRESS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".progress")
_progress = {"file": None, "last": 0.0}


def progress(phase, done, total, final=False):
    """Write how far it is (at most every 2 seconds, unless `final`)."""
    if not _progress["file"] or (not final and time.time() - _progress["last"] < 2):
        return
    _progress["last"] = time.time()
    try:
        os.makedirs(PROGRESS_DIR, exist_ok=True)
        tmp = _progress["file"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"phase": phase, "done": done, "total": total, "updated": time.time()}, f)
        os.replace(tmp, _progress["file"])
    except OSError:
        pass
TWO_TO_THREE = {"de": "deu", "en": "eng", "fr": "fra", "it": "ita", "es": "spa", "nl": "nld", "pt": "por",
                "cs": "ces", "pl": "pol", "ru": "rus", "hu": "hun", "sv": "swe", "da": "dan", "no": "nor", "fi": "fin"}


def tesseract():
    path = (os.environ.get("TESSERACT") or "").strip() or "tesseract"
    return shutil.which(path) or (path if os.path.isfile(path) else None)


def languages(binary):
    """The OCR languages: the setting (de,en or deu+eng), those installed."""
    wanted = [l.strip().lower() for l in re.split(r"[,+ ]", os.environ.get("OCR_LANGUAGES") or "de,en") if l.strip()]
    wanted = [TWO_TO_THREE.get(l, l) for l in wanted]
    try:
        out = subprocess.run([binary, "--list-langs"], capture_output=True, text=True, timeout=30)
        installed = {l.strip() for l in (out.stdout + out.stderr).splitlines()[1:] if l.strip()}
    except (OSError, subprocess.SubprocessError):
        installed = set()
    have = [l for l in wanted if l in installed] or (["eng"] if "eng" in installed else sorted(installed)[:1])
    return "+".join(have), [l for l in wanted if l not in installed]


def ones(n):
    return n.bit_count() if hasattr(n, "bit_count") else bin(n).count("1")  # Python < 3.10


def size(path):
    ffprobe = os.environ.get("STASH_FFPROBE") or "ffprobe"
    out = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "json", path], capture_output=True, text=True)
    stream = (json.loads(out.stdout or "{}").get("streams") or [{}])[0]
    if not stream.get("width"):
        raise SystemExit(f"ffprobe couldn't read the video: {out.stderr.strip()[-300:]}")
    return stream["width"], stream["height"]


def scan(path, duration=None):
    """{"cells": [[new standing edges per cell] per second], "size": [w, h],
    "grid": [columns, rows], "cell_bits": bits in a cell}.

    The picture, scaled down, as edges; per cell of a grid, the edges that
    stand (in this second's frame and the next one's) and are new (not in
    most of the frames 10 and 20 seconds before and after) are counted — a
    still stage or a logo is there all the time and drops out."""
    ffmpeg = os.environ.get("STASH_FFMPEG") or "ffmpeg"
    w, h = size(path)
    height = max(ROWS, round(WIDTH * h / w / ROWS) * ROWS)
    stride = (WIDTH + 7) // 8
    frame = stride * height
    total = frame * 8
    cw, ch = WIDTH // COLS, height // ROWS
    masks = []
    for r in range(ROWS):
        for c in range(COLS):
            x0, x1 = c * cw, (c + 1) * cw
            m = 0
            for y in range(r * ch, (r + 1) * ch):
                m |= ((1 << (x1 - x0)) - 1) << (total - (y * stride * 8 + x1))
            masks.append(m)
    proc = subprocess.Popen([ffmpeg, "-nostats", "-v", "error", "-threads", "0", "-i", path, "-an", "-sn", "-dn",
                             "-vf", f"fps=1,scale={WIDTH}:{height},format=gray,{EDGES},format=monob",
                             "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frames = []
    total = int(duration or 0) or None
    while True:
        data = proc.stdout.read(frame)
        if len(data) < frame:
            break
        frames.append(int.from_bytes(data, "big"))
        progress("scan", len(frames), total)
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0 and not frames:
        raise SystemExit(f"ffmpeg couldn't read the video: {err.strip()[-400:]}")
    cells = []
    for t in range(len(frames)):
        progress("compare", t, len(frames))
        if t + 1 >= len(frames):
            cells.append([0] * len(masks))
            continue
        standing = frames[t] & frames[t + 1]
        far = [frames[u] for u in (t - 20, t - 10, t + 11, t + 21) if 0 <= u < len(frames)]
        usual = far[0] if len(far) == 1 else 0  # in at least two of them
        for i in range(len(far)):
            for j in range(i + 1, len(far)):
                usual |= far[i] & far[j]
        new = standing & ~usual
        cells.append([ones(new & m) for m in masks] if new else [0] * len(masks))
    return {"cells": cells, "size": [w, h], "grid": [COLS, ROWS], "cell_bits": cw * ch}


def stretches(scanned):
    """[(first second, last second, (col0, row0, col1, row1), strength)]
    where text stood: a few cells with many more new standing edges than
    the rest of the picture (a still camera shot has them everywhere)."""
    cols, rows = scanned["grid"]
    least = MIN_SHARE * scanned["cell_bits"]
    seconds = []
    for values in scanned["cells"]:
        floor = statistics.median(values) if values else 0
        hot = {i for i, v in enumerate(values) if v > max(least, MIN_RISE * floor)}
        seconds.append(hot if 0 < len(hot) <= MAX_HOT * len(values) else set())
    found, t = [], 0
    while t < len(seconds):
        if not seconds[t]:
            t += 1
            continue
        cells, u = set(seconds[t]), t
        while u + 1 < len(seconds) and seconds[u + 1] and len(seconds[u + 1] & cells) * 3 >= min(len(seconds[u + 1]), len(cells)):
            u += 1
            cells |= seconds[u]
        span = range(t, u + 1)
        # the text's cells: hot in most of its seconds (the others: the
        # picture around it, moving now and then)
        cells = {i for i in cells if sum(i in seconds[x] for x in span) * 5 >= 2 * len(span)}
        t = u + 1
        if len(cells) < MIN_CELLS:
            continue  # a speck, not a line of text
        cs, rs = [i % cols for i in cells], [i // cols for i in cells]
        box = (min(cs), min(rs), max(cs) + 1, max(rs) + 1)
        if (box[2] - box[0]) * (box[3] - box[1]) > MAX_BOX * cols * rows:
            continue  # most of the picture: a still camera shot
        strength = sum(sum(scanned["cells"][x][i] for i in cells) for x in span)
        found.append((span[0], span[-1] + 1, box, strength))
    return found


def read_text(path, at, box, scanned, binary, langs):
    """The text at second `at` within `box` (grid cells), read by tesseract;
    "" if nothing worth reading (words it isn't sure of are dropped)."""
    ffmpeg = os.environ.get("STASH_FFMPEG") or "ffmpeg"
    (w, h), (cols, rows) = scanned["size"], scanned["grid"]
    c0, r0, c1, r1 = max(0, box[0] - 1), max(0, box[1] - 1), min(cols, box[2] + 1), min(rows, box[3] + 1)
    x, y = int(w * c0 / cols), int(h * r0 / rows)
    cw, ch = int(w * (c1 - c0) / cols) // 2 * 2, int(h * (r1 - r0) / rows) // 2 * 2
    scale = "scale=iw*2:ih*2," if h < 1000 else ""
    png = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1", "-an", "-sn",
                          "-vf", f"crop={cw}:{ch}:{x}:{y},{scale}format=gray", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True).stdout
    if not png:
        return ""
    out = subprocess.run([binary, "stdin", "stdout", "-l", langs, "--psm", "3", "tsv"], input=png,
                         capture_output=True).stdout.decode("utf-8", errors="replace")
    lines, confs = {}, []
    for row in out.splitlines()[1:]:
        cols_ = row.split("\t")
        if len(cols_) < 12 or cols_[0] != "5":
            continue
        try:
            conf = float(cols_[10])
        except ValueError:
            continue
        word = cols_[11].strip()
        if conf < 60 or not word or not re.search(r"\w", word):
            continue
        confs.append(conf)
        lines.setdefault((cols_[2], cols_[3], cols_[4]), []).append(word)
    text = "\n".join(" ".join(ws) for ws in lines.values()).strip()
    if sum(c.isalpha() for c in text) < 4 or not re.search(r"[^\W\d_]{3,}", text) or (confs and statistics.mean(confs) < 70):
        return ""
    return text


def similar(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8


def cached(path, key_extra, make):
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{key_extra}".encode()).hexdigest()
    cache = os.path.join(CACHE_DIR, key + ".json")
    try:
        with open(cache, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        pass
    value = make()
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(value, f)
        old = sorted((os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR)), key=os.path.getmtime)
        for stale in old[:-CACHE_KEEP]:
            os.remove(stale)
    except OSError:
        pass
    return value


def texts(path, duration):
    """(cues [(start, end, text)], notes)."""
    binary = tesseract()
    if not binary:
        raise SystemExit("tesseract isn't installed on the Stash server — it reads the text. Debian / Ubuntu: "
                         "apt install tesseract-ocr tesseract-ocr-deu; Stash's Docker image: apk add tesseract-ocr "
                         "tesseract-ocr-data-deu; or set its path in the plugin's settings.")
    langs, missing = languages(binary)
    scanned = cached(path, f"scan|{WIDTH}|{COLS}x{ROWS}|{EDGES}", lambda: scan(path, duration))
    found = stretches(scanned)
    seconds = len(scanned["cells"])
    skipped = 0
    if len(found) > MAX_READ:
        skipped = len(found) - MAX_READ
        found = sorted(sorted(found, key=lambda f: -f[3])[:MAX_READ], key=lambda f: f[0])

    def read_all():
        out = []
        for i, (a, b, box, _) in enumerate(found):
            progress("read", i, len(found))
            text = read_text(path, (a + b) / 2, box, scanned, binary, langs)
            if text:
                out.append([list(box), a, b, text])
        return out
    read = cached(path, f"read|{WIDTH}|{COLS}x{ROWS}|{EDGES}|{MIN_SHARE}|{MIN_RISE}|{MAX_HOT}|{langs}", read_all)

    # one text shown a little longer (read twice in a row): once
    merged = []
    for box, a, b, text in sorted(read, key=lambda r: r[1]):
        last = merged[-1] if merged else None
        if last and a - last[2] <= 2 and similar(last[3], text):
            last[2] = b
        else:
            merged.append([box, a, b, text])
    # a logo, a channel's name: there most of the time
    total = duration or seconds or 1
    shown = {}
    for box, a, b, text in merged:
        key = re.sub(r"\W+", "", text.lower())
        shown[key] = shown.get(key, 0) + (b - a)
    logos = {k for k, s in shown.items() if s > LOGO_SHARE * total}
    cues = sorted((float(a), float(b), text) for box, a, b, text in merged
                  if re.sub(r"\W+", "", text.lower()) not in logos)
    notes = (f"Scanned {seconds // 60} min of video (a frame a second), found {len(found)} place"
             f"{'' if len(found) == 1 else 's'} with text standing in the picture and could read {len(cues)} "
             f"(tesseract, {langs})")
    if logos:
        notes += f"; left out as a logo: {len(logos)} text{'' if len(logos) == 1 else 's'} shown most of the time"
    if skipped:
        notes += f"; {skipped} weaker places not read"
    if missing:
        notes += f"; not installed for tesseract: {', '.join(missing)}"
    return cues, notes + "."


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    files = [f for f in scene.get("files") or [] if os.path.isfile(f.get("path") or "")]
    if not files:
        raise SystemExit("The scene's video file isn't there (on the Stash server).")
    duration = files[0].get("duration")
    if scene.get("id"):
        name = re.sub(r"\W", "", str(scene["id"]))
        _progress["file"] = os.path.join(PROGRESS_DIR, name + ".json")
    try:
        cues, notes = texts(files[0]["path"], duration)
    finally:
        progress("done", 1, 1, final=True)
    if not cues:
        print(json.dumps({"markers": [], "notes": f"No text found in the picture. {notes}"}))
        return
    minutes = (duration or cues[-1][1]) / 60
    if len(cues) > max(20, 1.5 * minutes):
        # many texts: subtitles burned into the picture (an opera, a film) —
        # markers as from subtitles
        flat = [(a, b, " ".join(text.split())) for a, b, text in cues]
        markers, more = subtitles.markers_from(flat, duration)
        print(json.dumps({"markers": markers, "notes": f"{notes} Many texts — read as subtitles: {more}"}))
        return
    # a few: captions — "Sergej Rachmaninow / Klavierkonzert Nr. 3 op. 30 /
    # I. Allegro ma non tanto" — a marker each, where it shows
    markers = []
    for i, (a, b, text) in enumerate(cues):
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        end = cues[i + 1][0] if i + 1 < len(cues) else duration
        markers.append({"seconds": a, "end_seconds": end, "title": " – ".join(lines)})
    print(json.dumps({"markers": markers, "notes": f"{notes} Each text is a marker where it shows; captions are "
                      "often shown a little after the piece begins — the check against the audio suggests the "
                      "start. Credits and place names become markers too: untick them."}))


if __name__ == "__main__":
    main()
