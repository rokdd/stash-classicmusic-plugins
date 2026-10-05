"""Markers from text in the picture: captions ("Sergej Rachmaninow /
Klavierkonzert Nr. 3 / I. Allegro ma non tanto" at the lower left), title
cards, burned-in subtitles.

Kept simple:
  1. Where pieces begin: the start of the video and the 45 seconds after
     each pause in the audio (the whole video if there are no pauses).
  2. There, a frame every 4 seconds, the whole picture, read by tesseract.
  3. Words tesseract isn't sure of (under 60 %) are dropped; a line counts
     with two real words or more (three letters each, most of the line) —
     so a logo read as "NDRID", a backdrop's "Proms", bits of the picture
     ("=", "4") drop out.
  4. The same text in frames running is one text; a text in most of the
     frames (a channel's logo) is left out.
  5. Texts less than 30 seconds apart are one marker (a song's lines, a
     caption): titled by a caption in capitals if there's one, else by its
     first line.

Needs tesseract on the Stash server (Debian: apt install tesseract-ocr
tesseract-ocr-deu; Stash's Docker image: apk add tesseract-ocr
tesseract-ocr-data-deu) — the plugin setting "tesseract", else on the PATH.
What was read is remembered per file (in Stash's generated folder,
markers-as-chapters/frames).
"""

import concurrent.futures
import difflib
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subtitles  # noqa: E402 — markers from the texts, like from subtitles

STEP = 4  # seconds between the frames read
MAX_WIDTH = 1024  # wider pictures are scaled down for reading
TINY = (64, 36)  # the pictures compared to find frames the same as the one before …
SAME = 4  # … the same: the grey differs by less than this on average (of 255)
MIN_CONF = 60  # words tesseract is less sure of are dropped
PAUSE = (2.0, 20.0)  # pauses looked after: at least this long (s), this much quieter (dB) …
WEAK_PAUSE = (1.0, 15.0)  # … or, if there are none such, these
BEFORE, AFTER = 5, 45  # seconds looked at before a pause's end and after it
CHUNK = 60  # seconds read at a time (then saved)
GROUP_GAP = 30  # seconds: texts closer than this are one marker
MAX_WINDOWS = 80  # pauses looked after at most (the longest)
import storage  # noqa: E402 — where the analyses are kept (Stash's generated folder)
CACHE_DIR = storage.folder("frames")
CACHE_KEEP = 100
# How far it is, for the dialog: <generated>/markers-as-chapters/progress/<scene id>.json
PROGRESS_DIR = storage.folder("progress")
_progress = {"file": None, "last": 0.0, "started": None}
_reused = {"n": 0}


def progress(phase, done, total, final=False):
    """Write how far it is (at most every 2 seconds, unless `final`) — for the
    dialog, and as a Stash task for the task queue."""
    if not _progress["file"] or (not final and time.time() - _progress["last"] < 2):
        return
    if _progress.get("job") and phase == "read" and total:
        sys.stderr.write(f"\x01p\x02{min(1.0, done / total):.3f}\n")
        sys.stderr.flush()
    _progress["last"] = time.time()
    try:
        os.makedirs(PROGRESS_DIR, exist_ok=True)
        tmp = _progress["file"] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            if _progress["started"] is None or phase not in _progress.get("phases", ()):
                _progress["started"] = time.time()
                _progress["phases"] = (phase,)
                _progress["base"] = done  # what was done before (a run that goes on)
            json.dump({"phase": phase, "done": done, "total": total, "updated": time.time(),
                       "started": _progress["started"], "base": _progress.get("base", 0)}, f)
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
    # each language more is another reading of every frame: the first one
    # only, unless the OCR setting itself names more
    if not os.environ.get("OCR_EXPLICIT"):
        have = have[:1]
    return "+".join(have), [l for l in wanted if l not in installed]


def running(pid):
    """Is `pid` (still) one of ours? A process number left in a lock may be
    another program's by now: on Linux its command line tells."""
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            line = f.read().decode("utf-8", "replace")
        return "frames_ocr" in line or "marker_scrapers" in line
    except OSError:
        return True  # no /proc (macOS …): the process number alone


STALE = 1800  # seconds: a run whose progress hasn't moved for this long is taken as hung


def wait_for_other_run(progress_file, log=lambda line: None):
    """One scan per scene at a time: when another one is still running
    (asked again after a lost connection, say), wait for it — what it read
    is remembered, so this one is quick then. The lock file, or None."""
    if not progress_file:
        return None
    lock = progress_file[:-5] + ".lock"
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    waited = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                with open(lock, encoding="utf-8") as f:
                    pid = int(f.read().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            try:
                quiet = time.time() - os.path.getmtime(progress_file)
            except OSError:
                quiet = 0
            if not running(pid) or quiet > STALE:
                try:
                    os.remove(lock)  # left by a run that ended (or hung) without tidying up
                except OSError:
                    pass
                continue
            if not waited:
                log(f"Waiting for another reading of this scene to finish (process {pid}) …")
                waited = True
            time.sleep(5)
        except OSError:
            return None


def windows_for(path, duration):
    """[(start, length)] to look at, and how they were chosen. Captions
    come when a piece begins: the start of the video and the 45 seconds
    after each pause in the audio (from 5 seconds before its end). Without
    pauses (no audio, music throughout): the whole video."""
    try:
        import pauses
        levels = pauses.cached_loudness(path, os.environ.get("STASH_FFMPEG") or "ffmpeg")
    except BaseException:  # noqa: BLE001 — no audio: the whole video
        levels = []
    found = (pauses.find_pauses(levels, *PAUSE) or pauses.find_pauses(levels, *WEAK_PAUSE)) if levels else []
    end = duration or (levels[-1][0] if levels else 0)
    if not found or not end:
        return [(0.0, float(end or 0) or None)], "the whole video"
    if len(found) > MAX_WINDOWS:
        found = sorted(sorted(found, key=lambda p: p[0] - p[1])[:MAX_WINDOWS])
    spans = [(0.0, AFTER)] + [(max(0.0, b - BEFORE), b + AFTER) for a, b in found]
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, min(b, end)])
    return ([(round(a, 1), round(b - a, 1)) for a, b in merged if b - a > 3],
            f"the start and the {AFTER} seconds after each of {len(found)} pauses in the audio")


def frames(path, start, length, folder):
    """The window's frames, one every STEP seconds: [(time, PNG file, tiny
    grey picture)] — the tiny one to tell whether a frame is the same as the
    one before (then it needn't be read again)."""
    ffmpeg = os.environ.get("STASH_FFMPEG") or "ffmpeg"
    for old in os.listdir(folder):
        os.remove(os.path.join(folder, old))
    where = ["-ss", f"{start:.2f}"] if start else []
    span = ["-t", f"{length:.2f}"] if length else []
    graph = (f"[0:v:0]fps=1/{STEP},format=gray,split[a][b];[a]scale='min({MAX_WIDTH},iw)':-2[big];"
             f"[b]scale={TINY[0]}:{TINY[1]}[tiny]")
    # keyframes only (a full picture every second or two): decoding every
    # frame of a 50-fps broadcast to keep one in 200 took minutes per part
    proc = subprocess.run([ffmpeg, "-nostats", "-v", "error", "-skip_frame", "nokey", *where, "-i", path, *span,
                           "-an", "-sn", "-dn", "-filter_complex", graph, "-map", "[big]", os.path.join(folder, "%05d.png"),
                           "-map", "[tiny]", "-f", "rawvideo", "-"], capture_output=True)
    names = sorted(n for n in os.listdir(folder) if n.endswith(".png"))
    size = TINY[0] * TINY[1]
    tiny = [proc.stdout[i * size:(i + 1) * size] for i in range(len(proc.stdout) // size)]
    return [(start + i * STEP, os.path.join(folder, n), tiny[i] if i < len(tiny) else b"") for i, n in enumerate(names)]


def same_picture(a, b):
    """Two tiny grey pictures nearly the same (a still shot, the same
    caption still there)?"""
    if not a or not b or len(a) != len(b):
        return False
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) < SAME


def read_text(png, binary, langs):
    """What tesseract reads in the picture, line by line; "" if nothing."""
    out = subprocess.run([binary, png, "stdout", "-l", langs, "--psm", "11", "tsv"], capture_output=True,
                         env={**os.environ, "OMP_THREAD_LIMIT": "1"}).stdout.decode("utf-8", errors="replace")
    lines = {}
    for row in out.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        word = cols[11].strip()
        if conf >= MIN_CONF and word:
            lines.setdefault((cols[2], cols[3], cols[4]), []).append(word)
    text = "\n".join(" ".join(ws) for ws in lines.values()).strip()
    return text if re.search(r"[^\W\d_]{3,}", text) else ""


REAL_WORD = re.compile(r"^[^\W\d_]{3,}[.,!?'’…:;]*$")


def good_line(line):
    words = [w.strip("\"“”„'’()[]«»") for w in line.split()]
    real = [w for w in words if REAL_WORD.match(w)]
    return len(real) >= 2 and len(real) >= len(words) / 2


def similar(a, b):
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8


def logic():
    """A fingerprint of how the picture is read — the code and the settings
    that decide it. When it changes, what was read before isn't used (the
    cache depends on the analysis, not only on the file)."""
    import pauses
    parts = [inspect.getsource(f) for f in (windows_for, frames, read_text, pauses.find_pauses, pauses.loudness)]
    parts.append(repr((STEP, MAX_WIDTH, MIN_CONF, PAUSE, WEAK_PAUSE, BEFORE, AFTER, MAX_WINDOWS, pauses.WINDOW)))
    return hashlib.sha1("".join(parts).encode()).hexdigest()[:12]


def cache_file(path, key_extra):
    st = os.stat(path)
    key = hashlib.sha1(f"{path}|{st.st_size}|{st.st_mtime}|{key_extra}".encode()).hexdigest()
    return os.path.join(CACHE_DIR, key + ".json")


def cached(path, key_extra, make):
    cache = cache_file(path, key_extra)
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
        old = sorted((os.path.join(CACHE_DIR, n) for n in os.listdir(CACHE_DIR) if n.endswith(".json")),
                     key=os.path.getmtime)
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
    windows, chosen = windows_for(path, duration)
    progress("frames", 0, 0, final=True)
    total = sum(int((length or duration or 0) // STEP) + 1 for _, length in windows)

    key = f"read|{logic()}|{windows}|{langs}"
    # in pieces of at most a minute: what's read is saved after each, so a
    # run that's stopped goes on from there (also for a whole video)
    pieces = []
    for start, length in windows:
        length = length or duration or 0
        at = start
        while at < start + length - 0.01:
            pieces.append((at, min(CHUNK, start + length - at)))
            at += CHUNK
    partial = cache_file(path, key) + ".partial"

    def read_all():
        # what an earlier run that was stopped had read already: on from there
        try:
            with open(partial, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        out, done, reused = saved.get("out", []), saved.get("done", 0), saved.get("reused", 0)
        first = saved.get("windows", 0)
        if done:
            progress("read", done, max(total, done), final=True)  # on from where it was
        folder = tempfile.mkdtemp(prefix="markers-as-chapters-frames-")
        workers = max(1, min(8, (os.cpu_count() or 2) - 1))
        try:
            with concurrent.futures.ThreadPoolExecutor(workers) as pool:
                for w, (start, length) in enumerate(pieces):
                    if w < first:
                        continue
                    shots = frames(path, start, length, folder)
                    # a frame like the one before: its text again, not read again
                    jobs, previous = [], None
                    for at, png, tiny in shots:
                        if previous is not None and same_picture(tiny, previous[2]):
                            jobs.append((at, None))
                            reused += 1
                        else:
                            jobs.append((at, pool.submit(read_text, png, binary, langs)))
                            previous = (at, png, tiny)
                    last = ""
                    for at, job in jobs:
                        text = job.result() if job else last
                        last = text
                        done += 1
                        progress("read", done, max(total, done))
                        if text:
                            out.append([at, text])
                    try:  # saved after each part: a run stopped goes on from here
                        with open(partial + ".tmp", "w", encoding="utf-8") as f:
                            json.dump({"windows": w + 1, "out": out, "done": done, "reused": reused}, f)
                        os.replace(partial + ".tmp", partial)
                    except OSError:
                        pass
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        _reused["n"] = reused
        return out
    read = cached(path, key, read_all)
    # only lines with two real words or more (three letters each, most of the
    # line): a channel's logo read as "NDRID", a backdrop's "Proms", bits of
    # the picture ("=", "4") drop out — applied after reading, so changing it
    # doesn't read the video again
    read = [[at, "\n".join(lines)] for at, text in read
            for lines in [[line for line in text.splitlines() if good_line(line)]] if lines]
    try:
        os.remove(partial)
    except OSError:
        pass

    # a logo, a channel's name: in most of the frames
    counts = {}
    for _, text in read:
        key = re.sub(r"\W+", "", text.lower())
        counts[key] = counts.get(key, 0) + 1
    logos = {k for k, n in counts.items() if n > max(3, total / 2)}
    # the same text in frames running: one text
    cues = []
    for at, text in read:
        if re.sub(r"\W+", "", text.lower()) in logos:
            continue
        if cues and at - cues[-1][1] <= STEP and similar(cues[-1][2], text):
            cues[-1][1] = at + STEP
        else:
            cues.append([float(at), float(at + STEP), text])
    notes = (f"Looked at {chosen}: {total} frames (one every {STEP} s"
             + (f", {_reused['n']} the same as the one before" if _reused["n"] else "") + f"), text in {len(read)} of them, "
             f"{len(cues)} different text{'' if len(cues) == 1 else 's'} (tesseract, {langs})")
    if logos:
        notes += f"; left out as a logo: {len(logos)} text{'' if len(logos) == 1 else 's'} in most frames"
    if missing:
        notes += f"; not installed for tesseract: {', '.join(missing)}"
    return [tuple(c) for c in cues], notes + "."


def result(scene, path, duration):
    """The scraper's answer: {"markers", "notes"}."""
    cues, notes = texts(path, duration)
    if not cues:
        return {"markers": [], "notes": f"No text found in the picture. {notes}"}
    # texts close together are one piece (a song's lines, a caption and what
    # follows): a marker where the group begins, titled by a caption in
    # capitals if there's one (a piece's name), else by its first line
    groups = []
    for a, b, text in cues:
        if groups and a - groups[-1][-1][1] <= GROUP_GAP:
            groups[-1].append((a, b, text))
        else:
            groups.append([(a, b, text)])
    markers = []
    for i, g in enumerate(groups):
        lines = [" ".join(line.split()) for _, _, text in g for line in text.splitlines() if line.strip()]
        caps = [line for line in lines if sum(c.isupper() for c in line) > 0.6 * sum(c.isalpha() for c in line)]
        title = (caps or lines)[0].strip(" .…\"“”„")
        end = groups[i + 1][0][0] if i + 1 < len(groups) else duration
        markers.append({"seconds": g[0][0], "end_seconds": end, "title": title})
    return {"markers": markers, "notes": f"{notes} Texts less than {GROUP_GAP} s apart are one marker (a song's lines, "
            "a caption): titled by a caption in capitals if there's one, else by its first line. Captions often come a "
            "little after the piece begins — the check against the audio suggests the start."}


# Stash ends a plugin's process when the browser's request ends (the dialog
# closed, the page reloaded, a proxy's time limit) — too soon for a long
# concert. So the reading runs as a Stash task (the job queue: Settings →
# Tasks, stoppable there): the scraper answers "start a task" (the plugin
# starts it) or "running"; the dialog shows how far it is and asks again
# when it's done — then the answer is there (<scene>.result.json, for this
# file and this way of reading).

def signature(path):
    st = os.stat(path)
    binary = tesseract()
    langs = languages(binary)[0] if binary else ""
    # the reading's fingerprint and the one of what's made of it afterwards
    # (lines kept, groups): a change there makes the markers again from what
    # was read, without reading again
    after = hashlib.sha1("".join(inspect.getsource(f) for f in (texts, result, good_line)).encode()).hexdigest()[:12]
    return f"{path}|{st.st_size}|{st.st_mtime}|{logic()}|{langs}|{after}"


def lock_alive(progress_file):
    try:
        with open(progress_file[:-5] + ".lock", encoding="utf-8") as f:
            return running(int(f.read().strip() or 0))
    except (OSError, ValueError):
        return False


def files_for(scene):
    name = re.sub(r"\W", "", str(scene.get("id") or "x"))
    return os.path.join(PROGRESS_DIR, name + ".json"), os.path.join(PROGRESS_DIR, name + ".result.json")


def run_job(scene, log=lambda line: None):
    """The reading itself — run as a Stash task (marker_ocr_job)."""
    files = [f for f in scene.get("files") or [] if os.path.isfile(f.get("path") or "")]
    if not files:
        raise SystemExit("The scene's video file isn't there (on the Stash server).")
    path, duration = files[0]["path"], files[0].get("duration")
    progress_file, result_file = files_for(scene)
    _progress["file"], _progress["job"] = progress_file, True
    log(f"Text in the picture: {os.path.basename(path)} …")
    lock = wait_for_other_run(progress_file, log)
    progress("audio", 0, 0, final=True)
    try:
        answer = result(scene, path, duration)
        answer["signature"] = signature(path)
    except SystemExit as exc:
        answer = {"markers": [], "notes": str(exc.code), "signature": signature(path)}
    finally:
        progress("done", 1, 1, final=True)
        if lock:
            try:
                os.remove(lock)
            except OSError:
                pass
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(answer, f)
    log(f"Text in the picture: {len(answer['markers'])} markers for {os.path.basename(path)}. {answer.get('notes', '')}")
    return answer


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    files = [f for f in scene.get("files") or [] if os.path.isfile(f.get("path") or "")]
    if not files:
        raise SystemExit("The scene's video file isn't there (on the Stash server).")
    if not tesseract():
        texts(files[0]["path"], None)  # says what's missing
    path = files[0]["path"]
    progress_file, result_file = files_for(scene)
    try:
        with open(result_file, encoding="utf-8") as f:
            answer = json.load(f)
        if answer.get("signature") == signature(path):
            answer.pop("signature", None)
            print(json.dumps(answer))
            return
    except (OSError, ValueError):
        pass
    print(json.dumps({"markers": [], "running": True, "start_job": not lock_alive(progress_file), "notes":
                      "Reading the picture as a Stash task (Settings → Tasks) — it goes on when this dialog is closed."}))


if __name__ == "__main__":
    main()
