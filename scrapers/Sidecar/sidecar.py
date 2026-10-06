"""Stash scene scraper: the files next to the scene's video.

Run by Stash for "Scrape with… → Sidecar / local files" with the scene on
stdin (its id, title, URLs …). Stash doesn't pass the scene's file, so its
path is asked from Stash's own API on this machine: STASH_URL (default
http://localhost:9999), STASH_API_KEY if Stash has a login.

Read, next to the video (the first file of the scene):
  - medici.tv's JSON for the programme (as its site has it): <video>.json,
    <video>.medici.json, or any JSON of medici.tv in the folder if it's the
    only one or its name matches the video's — title, description, date,
    cast and composers as performers, director, festival and venue as tags;
  - a Kodi / Jellyfin NFO: <video>.nfo, else movie.nfo / musicvideo.nfo in
    the folder — title, plot, date, studio, director, actors, genres, tags;
  - a VDR recording (the Linux video recorder: <Title>/<date.time….rec>/
    001.vdr or 00001.ts): its programme guide entry ("info" / "info.vdr":
    title, subtitle, description, channel, broadcast start), else what the
    folder names say (title, broadcast date);
  - yt-dlp's info file: <video>.info.json — title, description, date, the
    channel as studio, the page, tags;
  - a cover: <video>.jpg / .png / -poster.jpg / -thumb.jpg / -fanart.jpg,
    or poster / folder / cover / thumb .jpg / .png in the folder.
Several of them: medici.tv first, then the NFO, then VDR's, then yt-dlp's file. Standard
library only.
"""

import base64
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


# -- the scene's files ----------------------------------------------------------------

def scene_files(scene_id):
    base = os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("STASH_API_KEY"):
        headers["ApiKey"] = os.environ["STASH_API_KEY"]
    body = json.dumps({"query": "query($id: ID!) { findScene(id: $id) { files { path } } }", "variables": {"id": scene_id}})
    request = urllib.request.Request(f"{base}/graphql", data=body.encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [f["path"] for f in ((data.get("data") or {}).get("findScene") or {}).get("files") or []]


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def load_json(path):
    try:
        return json.loads(read_text(path))
    except (OSError, ValueError):
        return None


def words(text):
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 2}


def plain(text):
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", text or "")
    text = html.unescape(re.sub(r"<[^>]+>", "", text)).replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", l).strip() for l in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# -- medici.tv ----------------------------------------------------------------------------

def is_medici(data):
    return isinstance(data, dict) and "slug" in data and any(k in data for k in ("casting", "chapters", "synopsis"))


def medici_file(video):
    stem = os.path.splitext(video)[0]
    for path in (stem + ".medici.json", stem + ".json", video + ".json"):
        data = load_json(path) if os.path.isfile(path) else None
        if is_medici(data):
            return data
    folder = os.path.dirname(video)
    found = []
    for name in sorted(os.listdir(folder)):
        if name.lower().endswith(".json") and not name.lower().endswith(".info.json"):
            data = load_json(os.path.join(folder, name))
            if is_medici(data):
                found.append((name, data))
    if len(found) == 1:
        return found[0][1]
    video_words = words(os.path.basename(stem))
    scored = sorted(((len(video_words & (words(n) | words(d.get("title")) | words(d.get("slug")))), d) for n, d in found),
                    key=lambda x: -x[0])
    if scored and scored[0][0] >= 2 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def from_medici(data):
    title = (data.get("title") or "").strip()
    subtitle = (data.get("subtitle") or "").strip()
    if subtitle and "(" not in subtitle:
        title = f"{title} – {subtitle}"
    rec = str(data.get("recording_date") or "").strip()
    date = rec[:10] if re.match(r"\d{4}-\d{2}-\d{2}", rec) else rec if re.fullmatch(r"\d{4}", rec) else \
        (str(data.get("date_publish") or "")[:10] or None)
    performers = []
    for group in data.get("casting") or data.get("longCasting") or []:
        for entry in group if isinstance(group, list) else [group]:
            name = ((entry or {}).get("artist") or {}).get("name")
            if name:
                performers.append(name)
    director = None
    for part in re.split(r"\s+[—–]\s+|,\s+", subtitle):
        part = re.sub(r"^(with|mit|avec)\s+", "", part.strip(), flags=re.I)
        m = re.match(r"^(.+?)\s*\(([^)]*)\)$", part)
        if m:
            if "director" in m.group(2).lower():
                director = director or m.group(1).strip()
            else:
                performers.append(m.group(1).strip())
    composers = list(data.get("composers") or [])
    for chapter in data.get("chapters") or []:
        composers += ((chapter or {}).get("work") or {}).get("composers") or []
    directors = [d.get("name") for d in data.get("directors") or [] if d.get("name")]
    return {
        "title": title,
        "details": plain(data.get("synopsis") or "") or (subtitle if "(" in subtitle else ""),
        "date": date,
        "studio": "medici.tv",
        "director": directors[0] if directors else director,
        "performers": composers + performers,
        "tags": [e.get("name") for e in data.get("events") or [] if e.get("name")] +
                [p.get("name") for p in data.get("places") or [] if p.get("name")],
        "urls": [f"https://www.medici.tv{data['url']}"] if data.get("url") else [],
        "image_url": data.get("hero_picture") or data.get("picture"),
    }


# -- Kodi / Jellyfin NFO ------------------------------------------------------------------------

def nfo_file(video):
    stem = os.path.splitext(video)[0]
    folder = os.path.dirname(video)
    for path in (stem + ".nfo", video + ".nfo", os.path.join(folder, "movie.nfo"), os.path.join(folder, "musicvideo.nfo")):
        if os.path.isfile(path):
            return path
    return None


def from_nfo(path):
    text = read_text(path)
    start = text.find("<")
    try:
        root = ET.fromstring(text[start:] if start >= 0 else text)
    except ET.ParseError:
        return None

    def first(*tags):
        for t in tags:
            v = root.findtext(t)
            if v and v.strip():
                return v.strip()
        return None

    date = first("premiered", "aired", "releasedate", "dateadded")
    date = date[:10] if date and re.match(r"\d{4}-\d{2}-\d{2}", date) else (first("year") if (first("year") or "").isdigit() else None)
    performers = [a.findtext("name").strip() for a in root.findall("actor") if (a.findtext("name") or "").strip()]
    performers += [a.text.strip() for a in root.findall("artist") if (a.text or "").strip()]
    performers += [c.text.strip() for c in root.findall("composer") if (c.text or "").strip()]
    tags = [t.text.strip() for t in root.findall("genre") + root.findall("tag") if (t.text or "").strip()]
    thumb = next((t.text.strip() for t in root.findall("thumb") if (t.text or "").strip().startswith("http")), None)
    return {
        "title": first("title", "originaltitle"),
        "details": first("plot", "outline"),
        "date": date,
        "studio": first("studio"),
        "director": first("director"),
        "performers": performers,
        "tags": tags,
        "urls": [u.text.strip() for u in root.findall("url") if (u.text or "").strip().startswith("http")],
        "image_url": thumb,
    }


# -- yt-dlp's info file --------------------------------------------------------------------------

def from_info_json(video):
    stem = os.path.splitext(video)[0]
    data = load_json(stem + ".info.json") if os.path.isfile(stem + ".info.json") else None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("release_date") or data.get("upload_date") or "")
    date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if re.fullmatch(r"\d{8}", raw) else None
    performers = [p for p in [data.get("artist"), data.get("creator")] if p]
    return {
        "title": data.get("title"),
        "details": data.get("description"),
        "date": date,
        "studio": data.get("channel") or data.get("uploader"),
        "director": None,
        "performers": performers,
        "tags": list(data.get("tags") or [])[:30],
        "urls": [u for u in [data.get("webpage_url")] if u],
        "image_url": data.get("thumbnail"),
    }


# -- a VDR recording ------------------------------------------------------------------------------
#
# VDR (the Linux video recorder) keeps a recording as
#   <Title>/<YYYY-MM-DD.hh.mm.prio.life>.rec/001.vdr (002.vdr …)  — older VDRs
#   <Title>/<YYYY-MM-DD.hh.mm.n-n>.rec/00001.ts                    — newer ones
# with the programme guide's entry beside it in "info.vdr" / "info":
#   C <channel id> <channel name>   E <event id> <start (Unix time)> <duration> …
#   T <title>   S <subtitle>   D <description, "|" for new lines>
# Without that file the folder names still say a lot: the title ("_" for
# spaces, "#XX" for special characters, "%" before a cut recording) and the
# broadcast's start in the .rec folder's name.

REC = re.compile(r"^(\d{4}-\d{2}-\d{2})\.(\d{2})[.:](\d{2})\.[\d.-]+\.rec$")


def vdr_name(name):
    name = re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), name)
    return name.lstrip("%@").replace("_", " ").replace("~", " – ").strip()


def from_vdr(video):
    folder = os.path.dirname(video)
    rec = REC.match(os.path.basename(folder))
    info = {}
    for name in ("info", "info.vdr"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                raw = f.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")  # older VDRs
            for line in text.splitlines():
                if len(line) > 2 and line[1] == " ":
                    info.setdefault(line[0], line[2:].strip())
            break
    if not rec and not info:
        return None
    title = info.get("T") or (vdr_name(os.path.basename(os.path.dirname(folder))) if rec else None)
    if title and info.get("S") and info["S"].lower() not in title.lower():
        title = f"{title} – {info['S']}"
    date = rec.group(1) if rec else None
    event = (info.get("E") or "").split()
    if len(event) >= 2 and event[1].isdigit():
        import datetime
        date = datetime.datetime.fromtimestamp(int(event[1])).date().isoformat()
    channel = None
    if info.get("C"):
        parts = info["C"].split(None, 1)
        channel = parts[1].split(";")[0].strip() if len(parts) > 1 else None  # "NDR FS NDS;ARD": without the provider
    details = (info.get("D") or "").replace("|", "\n").strip() or None
    return {"title": title, "details": details, "date": date, "studio": channel, "director": None,
            "performers": [], "tags": [], "urls": [], "image_url": None}


# -- the cover ------------------------------------------------------------------------------------

def cover(video):
    stem = os.path.splitext(video)[0]
    folder = os.path.dirname(video)
    names = [stem + s + e for s in ("", "-poster", "-thumb", "-fanart", "-cover") for e in IMAGE_TYPES]
    names += [os.path.join(folder, n + e) for n in ("poster", "folder", "cover", "thumb", "fanart") for e in IMAGE_TYPES]
    for path in names:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                data = f.read()
            kind = IMAGE_TYPES[os.path.splitext(path)[1].lower()]
            return f"data:{kind};base64,{base64.b64encode(data).decode()}"
    return None


# -- together -------------------------------------------------------------------------------------

def merge(parts):
    """Field by field: the first source that has it (medici.tv, NFO, yt-dlp);
    performers, tags and URLs from all."""
    out = {}
    for key in ("title", "details", "date", "studio", "director", "image_url"):
        out[key] = next((p[key] for p in parts if p.get(key)), None)
    for key in ("performers", "tags", "urls"):
        seen, merged = set(), []
        for p in parts:
            for v in p.get(key) or []:
                if v and v.lower() not in seen:
                    seen.add(v.lower())
                    merged.append(v)
        out[key] = merged
    return out


def main():
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if not data.get("id"):
        raise SystemExit("Use Scrape with… on a scene — the scraper needs the scene to find its files.")
    files = scene_files(data["id"])
    if not files:
        raise SystemExit("Stash has no file for this scene.")
    video = files[0]
    parts, sources = [], []
    medici = medici_file(video)
    if medici:
        parts.append(from_medici(medici))
        sources.append("medici.tv JSON")
    nfo = nfo_file(video)
    if nfo:
        found = from_nfo(nfo)
        if found:
            parts.append(found)
            sources.append(os.path.basename(nfo))
    recording = from_vdr(video)
    if recording:
        parts.append(recording)
        sources.append("VDR recording" + (" (programme guide)" if recording.get("details") or recording.get("studio") else
                                         " (folder names)"))
    info = from_info_json(video)
    if info:
        parts.append(info)
        sources.append("yt-dlp info")
    image = cover(video)
    if not parts and not image:
        raise SystemExit("No medici.tv JSON, NFO, VDR recording info, .info.json or cover image next to the video.")
    s = merge(parts) if parts else {}
    result = {}
    if s.get("title"):
        result["title"] = s["title"]
    if s.get("details"):
        result["details"] = s["details"]
    if s.get("date"):
        result["date"] = s["date"]
    if s.get("studio"):
        result["studio"] = {"name": s["studio"]}
    if s.get("director"):
        result["director"] = s["director"]
    if s.get("performers"):
        result["performers"] = [{"name": p} for p in s["performers"]]
    if s.get("tags"):
        result["tags"] = [{"name": t} for t in s["tags"]]
    urls = list(dict.fromkeys((s.get("urls") or []) + list(data.get("urls") or [])))
    if urls:
        result["urls"] = urls
    if image or s.get("image_url"):
        result["image"] = image or s["image_url"]
    # "\x01i\x02": Stash's log level marker — information, not an error
    sys.stderr.write(f"\x01i\x02Sidecar: read {', '.join(sources + (['cover image'] if image else []))}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    # Stash reads the result from stdout: always give it JSON — "null" when
    # there's nothing — and the reason in its log (stderr).
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            sys.stderr.write(f"Sidecar: {exc.code}\n")
            print("null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Sidecar: {type(exc).__name__}: {exc}\n")
        print("null")
