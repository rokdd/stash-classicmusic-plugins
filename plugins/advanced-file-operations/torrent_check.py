"""
Torrent check — part of the Advanced File Operations plugin.

Reads every .torrent file in a folder on the server, lists the videos in
each, and looks for each video in the Stash library by fuzzy file-name
matching. Returns a table (as JSON, through Stash's runPluginOperation) of
every torrent video next to its best-matching scene file: sizes, codec and
resolution on both sides, and how certain the match is, in percent.

Matching, per torrent video:
  - Both names are normalised: lower case, extension dropped, separators
    (. _ - + [ ] ( )) turned into spaces, and release tags that say
    nothing about the content (1080p, x265, WEB-DL, …) removed.
  - Candidates are the library files sharing at least one word with it;
    each is scored from the similarity of the two names (difflib) and how
    many of the torrent file's words the library name contains.
  - An identical file size makes it (almost) certain: that's the same
    file, whatever it's called now. A size within 2% counts a little.

Resolution and codec of a torrent video can't be read from a .torrent
file (it only has names and sizes), so they're guessed from its name —
"1080p", "x265" and the like — and shown as such.

Standard library only.
"""

import difflib
import os
import re

VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mkv", ".avi", ".wmv", ".mov", ".webm", ".mpg", ".mpeg",
    ".ts", ".m2ts", ".flv", ".vob", ".3gp",
}

# Words that describe a release, not its content — dropped before matching,
# so "Concert.2019.1080p.x265" and "Concert 2019" match fully.
NOISE_WORDS = {
    "2160p", "1080p", "1080i", "720p", "576p", "480p", "360p", "4k", "uhd", "fhd", "hd", "sd",
    "x264", "x265", "h264", "h265", "hevc", "avc", "av1", "vp9", "xvid", "divx", "10bit", "8bit",
    "hdr", "hdr10", "dv", "sdr", "aac", "ac3", "eac3", "dts", "flac", "mp3", "opus", "atmos",
    "ddp", "dd", "web", "webrip", "webdl", "dl", "bluray", "bdrip",
    "brrip", "hdtv", "dvdrip", "remux", "proper", "repack", "internal", "extended", "mp4", "mkv",
}

# Certainty (in %) from which a match counts as "in library", or at least
# a "possible match". Below that: "not found".
IN_LIBRARY_FROM = 85
POSSIBLE_FROM = 60


# ---------------------------------------------------------------------------
# .torrent files (bencode)
# ---------------------------------------------------------------------------

def bdecode(data, i=0):
    """Decodes one bencoded value starting at data[i]; returns (value, next i)."""
    c = data[i:i + 1]
    if c == b"i":
        end = data.index(b"e", i)
        return int(data[i + 1:end]), end + 1
    if c == b"l":
        i += 1
        items = []
        while data[i:i + 1] != b"e":
            value, i = bdecode(data, i)
            items.append(value)
        return items, i + 1
    if c == b"d":
        i += 1
        result = {}
        while data[i:i + 1] != b"e":
            key, i = bdecode(data, i)
            value, i = bdecode(data, i)
            result[key] = value
        return result, i + 1
    if c.isdigit():
        colon = data.index(b":", i)
        length = int(data[i:colon])
        start = colon + 1
        return data[start:start + length], start + length
    raise ValueError(f"not a bencoded value at byte {i}")


def _text(info, key):
    """A name field, preferring the explicit UTF-8 variant some clients add."""
    raw = info.get(key + b".utf-8", info.get(key, b""))
    if isinstance(raw, list):
        return "/".join(p.decode("utf-8", "replace") for p in raw)
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)


def read_torrent(path):
    """(torrent name, [(file path inside the torrent, size in bytes), ...])."""
    with open(path, "rb") as f:
        meta, _ = bdecode(f.read())
    info = meta[b"info"]
    name = _text(info, b"name")
    if b"files" in info:  # several files, inside a folder named `name`
        files = [(_text(entry, b"path"), int(entry[b"length"])) for entry in info[b"files"]]
    else:
        files = [(name, int(info[b"length"]))]
    return name, files


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[\s._\-+\[\](){},;&]+")


# Audio channel tags ("DDP5.1", "AAC2.0", "DD+ 7.1") as a whole — dropped
# before splitting, so their digits don't look like content. Other numbers
# stay: in "Symphony No. 5" the number is what tells it apart.
_CHANNELS_RE = re.compile(r"\b(?:ddp?|dd\+|aac|ac3|eac3|dts|truehd|atmos|flac|opus)?\s*[257]\.[01]\b")


def words(name):
    base = os.path.splitext(os.path.basename(name))[0].lower()
    base = _CHANNELS_RE.sub(" ", base)
    return [w for w in _SPLIT_RE.split(base) if w and w not in NOISE_WORDS]


def guess_resolution(name):
    n = name.lower()
    for pattern, label in (
        (r"2160p|\b4k\b|\buhd\b", "2160p"), (r"1080[pi]", "1080p"), (r"720p", "720p"),
        (r"576p", "576p"), (r"480p", "480p"),
    ):
        if re.search(pattern, n):
            return label
    return ""


def guess_codec(name):
    n = name.lower()
    for pattern, label in (
        (r"x265|h\.?265|hevc", "hevc"), (r"x264|h\.?264|\bavc\b", "h264"), (r"\bav1\b", "av1"),
        (r"\bvp9\b", "vp9"), (r"xvid", "xvid"), (r"divx", "divx"),
    ):
        if re.search(pattern, n):
            return label
    return ""


def certainty(torrent_words, torrent_size, lib_words, lib_size):
    """How sure (0–100) that a torrent file and a library file are the same."""
    if torrent_size and lib_size and torrent_size == lib_size:
        # Same size to the byte: the same file, whatever it's called now.
        return 99 if torrent_words and set(torrent_words) & set(lib_words) else 95
    if not torrent_words or not lib_words:
        return 0
    ratio = difflib.SequenceMatcher(None, " ".join(torrent_words), " ".join(lib_words)).ratio()
    shared = set(torrent_words) & set(lib_words)
    covered = len(shared) / len(set(torrent_words))
    score = 0.45 * ratio + 0.55 * covered
    # Numbers decide: "Symphony No. 5" and "Symphony No. 7" share every
    # other word. Numbers on both sides with none in common: a different
    # work, whatever else matches. Some in common but others clashing
    # (e.g. the same symphony, another year): much less sure.
    t_nums = {w for w in torrent_words if w.isdigit()}
    l_nums = {w for w in lib_words if w.isdigit()}
    if t_nums and l_nums and (t_nums - l_nums) and (l_nums - t_nums):
        score = min(score, 0.40) if not (t_nums & l_nums) else score - 0.15
    if torrent_size and lib_size and abs(torrent_size - lib_size) <= 0.02 * max(torrent_size, lib_size):
        score = min(1.0, score + 0.1)
    return round(score * 100)


def status_for(percent):
    if percent >= IN_LIBRARY_FROM:
        return "in_library"
    if percent >= POSSIBLE_FROM:
        return "possible"
    return "not_found"


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def library_files(gql):
    data = gql(
        "query { findScenes(filter: { per_page: -1 }) { scenes { id title files "
        "{ path basename size video_codec width height duration } } } }"
    )
    files = []
    for scene in data["findScenes"]["scenes"]:
        for f in scene.get("files") or []:
            files.append({
                "scene_id": scene["id"],
                "scene_title": scene.get("title") or "",
                "path": f.get("path") or "",
                "basename": f.get("basename") or os.path.basename(f.get("path") or ""),
                "size": int(f.get("size") or 0),
                "codec": f.get("video_codec") or "",
                "width": f.get("width") or 0,
                "height": f.get("height") or 0,
                "words": words(f.get("basename") or f.get("path") or ""),
            })
    return files


def run(gql, args, settings):
    # One or several folders, separated by ";".
    given = (args.get("folder") or settings.get("torrentFolder") or "").strip()
    folders = [f.strip() for f in given.split(";") if f.strip()]
    if not folders:
        raise ValueError("No torrent folder given — enter one, or set a default in the plugin's settings.")
    missing = [f for f in folders if not os.path.isdir(f)]
    if missing:
        raise ValueError("Torrent folder doesn't exist on the server: " + "; ".join(missing))

    library = library_files(gql)
    # Word → library files containing it, to only compare likely candidates.
    index = {}
    for i, f in enumerate(library):
        for w in set(f["words"]):
            index.setdefault(w, []).append(i)
    by_size = {}
    for i, f in enumerate(library):
        if f["size"]:
            by_size.setdefault(f["size"], []).append(i)

    rows, unreadable = [], []
    skipped_samples = 0
    torrent_paths = sorted(
        os.path.join(folder, n) for folder in folders for n in os.listdir(folder) if n.lower().endswith(".torrent")
    )
    for torrent_path in torrent_paths:
        try:
            torrent_name, files = read_torrent(torrent_path)
        except Exception as exc:  # noqa: BLE001
            unreadable.append({"file": os.path.basename(torrent_path), "error": str(exc)})
            continue
        videos = [(p, s) for p, s in files if os.path.splitext(p)[1].lower() in VIDEO_EXTENSIONS]
        # Sample clips ("Sample/sample.mkv", "…-sample.mp4") aren't the
        # video itself: counted, not matched.
        samples = [(p, s) for p, s in videos if re.search(r"(^|[/\\._\- ])sample([/\\._\- ]|$)", p.lower())]
        skipped_samples += len(samples)
        videos = [v for v in videos if v not in samples]
        for inner_path, size in videos:
            t_words = words(inner_path)
            candidates = set(by_size.get(size, []))
            for w in set(t_words):
                bucket = index.get(w, [])
                if len(bucket) <= 500:  # a word in hundreds of files tells nothing
                    candidates.update(bucket)
            best, best_pct = None, 0
            for i in candidates:
                lib = library[i]
                pct = certainty(t_words, size, lib["words"], lib["size"])
                if pct > best_pct:
                    best, best_pct = lib, pct
            rows.append({
                "torrent": os.path.basename(torrent_path),
                "torrent_folder": os.path.dirname(torrent_path),
                "torrent_name": torrent_name,
                "file": inner_path,
                "size": size,
                "resolution_guess": guess_resolution(inner_path) or guess_resolution(torrent_name),
                "codec_guess": guess_codec(inner_path) or guess_codec(torrent_name),
                "certainty": best_pct,
                "status": status_for(best_pct),
                "match": None if not best else {
                    "scene_id": best["scene_id"],
                    "scene_title": best["scene_title"],
                    "basename": best["basename"],
                    "path": best["path"],
                    "size": best["size"],
                    "codec": best["codec"],
                    "resolution": f"{best['width']}×{best['height']}" if best["width"] else "",
                },
            })

    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("in_library", "possible", "not_found")}
    return {
        "folder": "; ".join(folders),
        "torrents": len(torrent_paths),
        "videos": len(rows),
        "library_files": len(library),
        "counts": counts,
        "rows": rows,
        "unreadable": unreadable,
        "skipped_samples": skipped_samples,
        "thresholds": {"in_library": IN_LIBRARY_FROM, "possible": POSSIBLE_FROM},
    }
