"""Marker scraper: markers from subtitles.

stdin: {"scene": {...}, "url": optional, "text": optional}
stdout: {"markers": [...], "notes": "..."}

Where the subtitles come from, the first that has some:
  - "text": subtitles pasted (SRT or WebVTT) — the Plain text scraper hands
    them over too;
  - a file next to the video: <video>.srt / .vtt / .ass, also with a
    language (<video>.de.srt …);
  - the video file's own subtitle track (text ones: SubRip, mov_text,
    WebVTT, ASS — read with ffmpeg; picture subtitles can't be read);
  - online, with yt-dlp: the URL given, else the scene's URLs (ARTE, ARD,
    ZDF, ORF … publish subtitles for some broadcasts).

Concert subtitles show what's said or shown, not the music: an
announcement, a title card, sung text in an opera. So:
  - entries less than 20 s apart make one group;
  - a short group (up to 2 entries, under 12 s — a title card, a sentence)
    gets a marker where it shows: the piece starts there;
  - a longer group (an announcement, a speech) gets a marker where it
    ends: the piece follows it;
  - its text is the title (composers named in it are found as with every
    scraper); music and applause markings (♪, "(Musik)", "[Applaus]") start
    and end music too; technical entries ("U/T", "Untertitel: …") don't count.
The review dialog's check against the audio then shows where the music
really starts.
"""

import glob
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

from encoding_fix import decode_bytes, fix_text

GROUP_GAP = 20.0  # seconds between entries that still belong together
SHORT = (2, 12.0)  # entries, seconds: a title card or a sentence
MIN_PIECE = 30.0  # seconds
MUSIC = re.compile(r"♪|♫|[(\[*]\s*(musik|music|gesang|singing|orchester|orchestra)[^)\]*]*[)\]*]", re.I)
APPLAUSE = re.compile(r"[(\[*]\s*(applaus|beifall|applause|jubel)[^)\]*]*[)\]*]", re.I)
TECHNICAL = re.compile(r"^(u\s*/\s*t|ut|untertitel.*|subtitles?.*|copyright.*|\(c\).*|©.*|www\..*|sous-titr.*)$", re.I)
# Words of an announcement: the piece follows it (even if it's short).
ANNOUNCE = re.compile(r"\b(es folgt|folgt|wir beginnen|wir hören|hören sie|jetzt|nun|als nächstes|zum abschluss|zugabe|"
                      r"next|now|we begin|you will hear|followed by|to finish)\b", re.I)
# How announcements begin — taken off the title.
LEAD = re.compile(r"^(?:und\s+)?(?:nun|jetzt|es folgt|als nächstes|wir beginnen(?: mit)?|wir hören|hören sie(?: jetzt)?|"
                  r"zum abschluss|zum schluss|zugabe|now|next|we begin with|you will hear|and finally)\s*[:,]?\s*"
                  r"(?:der|die|das|den|dem|ein|eine|einen|the|a)?\s+", re.I)
MUSIC_WORDS = {"musik", "music", "gesang", "singing", "orchester", "orchestra", "instrumental"}
TIME = r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{1,3})|(\d{1,2}):(\d{2})[.,](\d{1,3})"


# -- reading subtitles -----------------------------------------------------------------

def _seconds(m):
    g = m.groups()
    if g[0] is not None:
        return int(g[0]) * 3600 + int(g[1]) * 60 + int(g[2]) + int(g[3].ljust(3, "0")) / 1000
    return int(g[4]) * 60 + int(g[5]) + int(g[6].ljust(3, "0")) / 1000


def _clean(text):
    text = re.sub(r"<[^>]+>|\{[^}]*\}", "", text)  # <i>, <c.yellow>, {\an8}
    text = text.replace("\\N", " ").replace("\\n", " ")
    return re.sub(r"\s+", " ", fix_text(text)).strip()


def parse(text):
    """[(start, end, text)] from SRT, WebVTT or ASS."""
    cues = []
    if re.search(r"^\[Events\]", text, re.M):  # ASS / SSA
        for line in text.splitlines():
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) == 10:
                    def t(v):
                        h, m, s = v.strip().split(":")
                        return int(h) * 3600 + int(m) * 60 + float(s)
                    cues.append((t(parts[1]), t(parts[2]), _clean(parts[9])))
        return [c for c in cues if c[2]]
    arrow = re.compile(rf"({TIME})\s*-->\s*({TIME})")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = arrow.search(line)
            if m:
                start = _seconds(re.match(TIME, m.group(1)))
                end = _seconds(re.match(TIME, m.group(9)))
                body = _clean(" ".join(lines[i + 1:]))
                if body:
                    cues.append((start, end, body))
                break
    return sorted(cues)


def looks_like_subtitles(text):
    return bool(re.search(rf"({TIME})\s*-->\s*({TIME})", text or "")) or bool(re.search(r"^\[Events\]", text or "", re.M))


def beside(video):
    base = os.path.splitext(video)[0]
    found = []
    for ext in ("srt", "vtt", "ass", "ssa"):
        found += [base + "." + ext] + sorted(glob.glob(glob.escape(base) + ".*." + ext))
    for path in found:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return decode_bytes(f.read()), os.path.basename(path)
    return None, None


def embedded(video):
    ffmpeg = os.environ.get("STASH_FFMPEG") or "ffmpeg"
    out = subprocess.run([ffmpeg, "-v", "error", "-i", video, "-map", "0:s:0", "-f", "srt", "-"],
                         capture_output=True, timeout=300)
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return decode_bytes(out.stdout)


def online(url):
    ytdlp = os.environ.get("STASH_YTDLP") or "yt-dlp"
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [ytdlp, "--skip-download", "--write-subs", "--no-warnings", "--no-playlist",
               "--sub-langs", "de.*,deu.*,ger.*,en.*,eng.*,und,fr.*", "--sub-format", "vtt/srt/best",
               "-o", os.path.join(tmp, "subs.%(ext)s"), url]
        ffmpeg = os.environ.get("STASH_FFMPEG") or ""
        if os.path.isabs(ffmpeg):
            cmd[1:1] = ["--ffmpeg-location", os.path.dirname(ffmpeg), "--convert-subs", "srt"]
        subprocess.run(cmd, capture_output=True, timeout=180)
        files = sorted(glob.glob(os.path.join(tmp, "subs.*")),
                       key=lambda p: (0 if re.search(r"\.(de|deu|ger)", p) else 1, p))
        for path in files:
            if path.endswith((".srt", ".vtt", ".ass")):
                with open(path, "rb") as f:
                    return decode_bytes(f.read()), os.path.basename(path)
    return None, None


# -- OpenSubtitles ---------------------------------------------------------------------------
#
# opensubtitles.com's API (the old .org one is closed): needs an API key —
# free, at opensubtitles.com under "API consumers" — and, to download, the
# account's username and password (a free account allows about 20 downloads
# a day). From the plugin's settings, handed over as OS_API_KEY, OS_USERNAME,
# OS_PASSWORD, OS_LANGUAGES. Searched by the file's fingerprint (exact: the
# same release someone made the subtitles for), else by the scene's title.

OS_API = "https://api.opensubtitles.com/api/v1"
OS_AGENT = "StashMarkersAsChapters v1.0"


def moviehash(path):
    """OpenSubtitles' fingerprint of a file: its size plus the 64-bit words
    of its first and last 64 KB, summed."""
    size = os.path.getsize(path)
    if size < 131072:
        return None
    total = size
    with open(path, "rb") as f:
        for offset in (0, size - 65536):
            f.seek(offset)
            chunk = f.read(65536)
            for (word,) in struct.iter_unpack("<Q", chunk):
                total = (total + word) & 0xFFFFFFFFFFFFFFFF
    return f"{total:016x}"


def _os_request(url, key, method="GET", body=None, token=None):
    headers = {"Api-Key": key, "User-Agent": OS_AGENT, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("message")
        except Exception:  # noqa: BLE001
            detail = None
        raise RuntimeError(f"OpenSubtitles: {detail or exc}") from None


def opensubtitles(scene):
    """(subtitles text, where they're from) or (None, why not)."""
    key = os.environ.get("OS_API_KEY", "").strip()
    if not key:
        return None, ("no OpenSubtitles API key in the settings (Markers as Chapters → OpenSubtitles API key; "
                      "free at opensubtitles.com under API consumers)")
    languages = ",".join(sorted(l.strip().lower() for l in (os.environ.get("OS_LANGUAGES") or "de,en").split(",") if l.strip()))
    order = [l.strip().lower() for l in (os.environ.get("OS_LANGUAGES") or "de,en").split(",") if l.strip()]
    files = scene.get("files") or []
    found, how = [], ""
    if files and os.path.isfile(files[0]["path"]):
        h = moviehash(files[0]["path"])
        if h:
            found = _os_request(f"{OS_API}/subtitles?" + urllib.parse.urlencode({"languages": languages, "moviehash": h}), key).get("data") or []
            found = [s for s in found if (s.get("attributes") or {}).get("moviehash_match")] or found
            how = "the file's fingerprint"
    if not found:
        query = re.sub(r"\.[a-z0-9]{2,4}$", "", scene.get("title") or "", flags=re.I)
        query = re.sub(r"[._]+", " ", query).strip()
        if query:
            found = _os_request(f"{OS_API}/subtitles?" + urllib.parse.urlencode({"languages": languages, "query": query.lower()}), key).get("data") or []
            how = f"the title “{query}”"
    if not found:
        return None, f"OpenSubtitles has nothing for this scene (searched by {how or 'its file and title'})"

    def rank(s):
        a = s.get("attributes") or {}
        lang = (a.get("language") or "").lower()
        return (0 if a.get("moviehash_match") else 1, order.index(lang) if lang in order else len(order),
                -(a.get("download_count") or 0))
    best = sorted(found, key=rank)[0]["attributes"]
    file_id = ((best.get("files") or [{}])[0]).get("file_id")
    if not file_id:
        return None, "OpenSubtitles found subtitles, but without a file to download"
    token, base = None, OS_API
    if os.environ.get("OS_USERNAME") and os.environ.get("OS_PASSWORD"):
        login = _os_request(f"{OS_API}/login", key, "POST",
                            {"username": os.environ["OS_USERNAME"], "password": os.environ["OS_PASSWORD"]})
        token = login.get("token")
        if login.get("base_url"):
            base = f"https://{login['base_url']}/api/v1"
    link = _os_request(f"{base}/download", key, "POST", {"file_id": file_id, "sub_format": "srt"}, token)
    if not link.get("link"):
        return None, f"OpenSubtitles didn't give a download ({link.get('message') or 'no link'})"
    with urllib.request.urlopen(urllib.request.Request(link["link"], headers={"User-Agent": OS_AGENT}), timeout=60) as response:
        text = decode_bytes(response.read())
    title = (best.get("feature_details") or {}).get("title") or best.get("release") or "?"
    left = f", {link.get('remaining')} downloads left today" if link.get("remaining") is not None else ""
    return text, f"OpenSubtitles — “{title}” ({best.get('language')}, found by {how}{left})"


# -- from subtitles to markers ------------------------------------------------------------

def announced(text):
    """What an announcement announces: its last sentence, without the
    lead-in — "Guten Abend … Wir beginnen mit Franz von Suppè:
    Fatinitza-Marsch." → "Franz von Suppè: Fatinitza-Marsch"."""
    sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]
    if not sentences:
        return text
    last = sentences[-1]
    if len(last) < 15 and len(sentences) > 1:
        last = f"{sentences[-2]} {last}"
    last = LEAD.sub("", last).strip(" .")
    return last[:1].upper() + last[1:] if last else text


def markers_from(cues, duration=None):
    """(markers, notes) — see the module's description."""
    cues = [c for c in cues if not TECHNICAL.match(c[2])]
    if not cues:
        return [], "The subtitles have nothing but technical entries."
    groups = []
    for cue in cues:
        if groups and cue[0] - groups[-1][-1][1] <= GROUP_GAP:
            groups[-1].append(cue)
        else:
            groups.append([cue])
    def words_of(text):
        text = APPLAUSE.sub("", text)
        text = re.sub(r"[♪♫]", " ", MUSIC.sub(lambda m: m.group(0) if "♪" in m.group(0) else "", text))
        text = text.strip(" ,;-")  # full stops stay: they end the sentences
        return "" if text.strip(" .").lower() in MUSIC_WORDS or not text.strip(" .") else text

    starts, breaks = [], []
    for g in groups:
        music = [c for c in g if MUSIC.search(c[2])]
        words = [w for w in (words_of(c[2]) for c in g) if w]
        title = re.sub(r"\s+", " ", " ".join(words))[:140].strip()
        span = g[-1][1] - g[0][0]
        if not words and not music:
            breaks.append(g[0][0])  # applause alone: the music before it ends here
        elif music and not words:
            starts.append((music[0][0], "", "music"))  # just ♪: music from here
        elif len(g) <= SHORT[0] and span <= SHORT[1] and not ANNOUNCE.search(title):
            starts.append((g[0][0], title.strip(" ."), "card"))  # a title card: the piece starts here
        else:
            after = next((c[0] for c in g if MUSIC.search(c[2]) and c[0] > g[0][0]), None)
            starts.append((after if after is not None else g[-1][1], announced(title), "after"))
    markers = []
    for i, (t, title, kind) in enumerate(starts):
        nxt = starts[i + 1][0] if i + 1 < len(starts) else (duration or None)
        ends = [b for b in breaks if t < b < (nxt if nxt is not None else float("inf"))]
        end = ends[0] if ends else nxt
        if end is not None and end - t < MIN_PIECE and kind != "card":
            continue
        markers.append({"seconds": round(t, 2), "end_seconds": round(end, 2) if end else None,
                        "title": title or f"Part {len(markers) + 1}", "kind": kind})
    cards = sum(1 for m in markers if m.pop("kind") == "card")
    notes = (f"{len(cues)} subtitle entries in {len(groups)} groups: {len(markers)} marker{'' if len(markers) == 1 else 's'} — "
             f"{cards} where a short text (a title card) shows, the others after an announcement or at a music marking. "
             "The titles are the subtitles' text — shorten them, and check the starts against the audio.")
    return markers, notes


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    files = scene.get("files") or []
    duration = max([f.get("duration") or 0 for f in files] or [0]) or None
    if sys.argv[1:2] == ["opensubtitles"]:
        try:
            text, source = opensubtitles(scene)
        except Exception as exc:  # noqa: BLE001 — the reason, in the dialog
            text, source = None, str(exc)
        if not text:
            print(json.dumps({"markers": [], "notes": f"No subtitles: {source}."}))
            return
        cues = parse(text)
        markers, notes = markers_from(cues, duration)
        print(json.dumps({"markers": markers, "notes": f"From {source}: {notes}"}))
        return
    text, source = payload.get("text") or "", "the pasted text"
    if not looks_like_subtitles(text):
        text = ""
        if payload.get("url"):
            text, source = online(payload["url"])
            source = f"{source} (online)" if text else source
        else:
            for f in files:
                text, source = beside(f["path"])
                if text:
                    source = f"{source} next to the video"
                    break
                text = embedded(f["path"]) if os.path.isfile(f["path"]) else None
                if text:
                    source = "the video file's subtitle track"
                    break
            if not text:
                for url in scene.get("urls") or []:
                    text, name = online(url)
                    if text:
                        source = f"{name} from {url}"
                        break
    if not text:
        print(json.dumps({"markers": [], "notes":
            "No subtitles found — none next to the video (.srt / .vtt / .ass), none in it (picture subtitles can't be "
            "read), and none online for the scene's URLs. Concerts often have none at all."}))
        return
    cues = parse(text)
    if not cues:
        print(json.dumps({"markers": [], "notes": f"Couldn't read subtitles from {source}."}))
        return
    markers, notes = markers_from(cues, duration)
    print(json.dumps({"markers": markers, "notes": f"From {source}: {notes}"}))


if __name__ == "__main__":
    main()
