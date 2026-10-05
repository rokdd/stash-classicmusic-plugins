"""Stash scene scraper: broadcasts of the German-language public media
libraries (ARD and its stations, ZDF, 3sat, ARTE, KiKA, Phoenix, ORF, SRF,
DW …) as MediathekView lists them — also those long gone, from its archive.

Two sources, both without an account:
  - MediathekViewWeb's search (mediathekviewweb.de/api/query): what's online
    now (plus what's announced);
  - MediathekView's archive (archiv.mediathekview.de): the whole film list as
    it was on each day since March 2015 — one file a day (25–80 MB, xz). A
    broadcast is in the lists of the days after it aired.

What a scene gets: title, description, broadcast date, the station as
studio, the Mediathek page as URL (for Classical Concerts to scrape the
performers from, if it's still there). MediathekView has no pictures.

Run by Stash (see MediathekView.yml) with one argument:
  name      stdin {"name": …}     → up to 15 broadcasts (search now online; with
                                    a date in the words, e.g. "proms 08.09.2018",
                                    that day's archive too)
  query     stdin one of those     → that broadcast
  fragment  stdin a scene          → the broadcast that fits the scene best:
                                    by its title (or its file's name), its date
                                    (or the file's date) and its file's length —
                                    online first, then in the archive

Standard library only. The scene's file (name, length, date) is looked up
through Stash's API on this machine (STASH_URL, default
http://localhost:9999; STASH_API_KEY if Stash has a login).
"""

import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.request

USER_AGENT = "Mozilla/5.0 (StashMediathekViewScraper; https://github.com/rokdd/stash-classicmusic-plugins)"
API = "https://mediathekviewweb.de/api/query"
ARCHIVE = "https://archiv.mediathekview.de/{y:04d}/{m:02d}/{y:04d}-{m:02d}-{d:02d}-filme.xz"
FIRST_ARCHIVE = datetime.date(2015, 3, 8)
AFTER_DAYS = (1, 7, 30)  # the archive's lists looked at: this many days after the broadcast
STOP = {"der", "die", "das", "und", "the", "and", "von", "mit", "for", "with", "auf", "aus", "ein", "eine",
        "des", "dem", "den", "hd", "sd", "mp4", "mkv", "avi", "m4v", "ts", "720p", "1080p", "fassung",
        "originalversion", "teil", "part", "folge",
        # words of every concert broadcast: they don't tell which one
        "arte", "concert", "concerts", "konzert", "klassik", "musik", "music", "live", "tipp", "kultur", "oper"}
LOG_INFO = "\x01i\x02"


def log(text):
    sys.stderr.write(f"{LOG_INFO}MediathekView: {text}\n")


# -- requests -----------------------------------------------------------------------------

def post_json(url, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"User-Agent": USER_AGENT, "Content-Type": "text/plain"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def stash(query, variables):
    base = os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("STASH_API_KEY"):
        headers["ApiKey"] = os.environ["STASH_API_KEY"]
    request = urllib.request.Request(f"{base}/graphql", data=json.dumps({"query": query, "variables": variables}).encode(),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return (json.loads(response.read().decode("utf-8")).get("data") or {})


# -- words and dates ----------------------------------------------------------------------------

def words(text):
    text = re.sub(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])", " ", text or "")  # "JubiläumskonzertMit" → two words
    return {w for w in re.split(r"[^\w]+", text.lower()) if len(w) > 2 and w not in STOP and not w.isdigit()}


def years(text):
    return {int(y) for y in re.findall(r"(?<!\d)((?:19|20)\d\d)(?!\d)", text or "")}


def date_in(text):
    """A date written in the text: 2018-09-08, 08.09.2018, 08.09.18."""
    m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", text or "")
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})(?!\d)", text or "")
        if not m:
            return None
        d, mo, y = map(int, m.groups())
        y += 2000 if y < 100 else 0
    try:
        return datetime.date(y, mo, d)
    except ValueError:
        return None


def seconds(text):
    """"01:34:00" → 5640."""
    parts = [int(p) for p in re.findall(r"\d+", text or "")]
    total = 0
    for p in parts[-3:]:
        total = total * 60 + p
    return total


# -- broadcasts → scenes ----------------------------------------------------------------------------

def scene_of(b, wanted=()):
    """A broadcast (MediathekView's fields, as in the search's answer) → a
    Stash scene. The topic goes before the title when it says more of what
    was looked for ("Last Night of the Proms 2018 – Live aus London")."""
    title, topic = b.get("title") or "", b.get("topic") or ""
    if topic and topic.lower() not in title.lower() and (set(wanted) & (words(topic) - words(title))):
        title = f"{topic} – {title}"
    out = {"title": title}
    if b.get("description"):
        out["details"] = re.sub(r"\n?\.{3,}$", "…", b["description"].strip())
    if b.get("timestamp"):
        out["date"] = datetime.datetime.fromtimestamp(int(b["timestamp"]), datetime.timezone.utc).date().isoformat()
    if b.get("channel"):
        out["studio"] = {"name": b["channel"]}
    if b.get("url_website"):
        out["urls"] = [b["url_website"]]
    return out


def search_online(text, size=50):
    """MediathekViewWeb's search: [broadcast], best first by its order."""
    body = {"queries": [{"fields": ["title", "topic"], "query": text}], "sortBy": "timestamp",
            "sortOrder": "desc", "future": True, "offset": 0, "size": size}
    return (post_json(API, body).get("result") or {}).get("results") or []


def _broadcast(x, channel, topic):
    return {"channel": x[0] or channel, "topic": x[1] or topic, "title": x[2], "date": x[3], "duration": seconds(x[5]),
            "description": x[7], "url_website": x[9],
            "timestamp": int(x[16]) if len(x) > 16 and str(x[16]).isdigit() else None}


class unpacked:
    """The xz file being downloaded, unpacked as text while it comes: with
    Python's lzma — or, where Python was built without it (seen: a Python
    3.8 in /usr/local), with the xz program."""

    def __init__(self, response):
        self.response, self.proc = response, None

    def __enter__(self):
        try:
            import lzma
            self.text = lzma.open(self.response, "rt", encoding="utf-8", errors="replace")
            return self.text
        except ImportError:
            pass
        xz = shutil.which("xz") or shutil.which("unxz")
        if not xz:
            raise SystemExit("can't unpack MediathekView's archive: this Python has no lzma module and the xz program "
                             "isn't installed (Debian / Ubuntu: apt install xz-utils; Alpine: apk add xz)")
        self.proc = subprocess.Popen([xz, "-dc"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)

        def feed():
            try:
                while True:
                    block = self.response.read(1 << 20)
                    if not block:
                        break
                    self.proc.stdin.write(block)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass
        threading.Thread(target=feed, daemon=True).start()
        self.text = io.TextIOWrapper(self.proc.stdout, encoding="utf-8", errors="replace")
        return self.text

    def __exit__(self, *exc):
        try:
            self.text.close()
        except (OSError, AttributeError):
            pass
        if self.proc:
            self.proc.kill()
            self.proc.wait()
        return False


def archive_list(day, needles=()):
    """The broadcasts in the archive's list of `day`, one after the other (as
    dicts like the search's), read while it downloads — a few MB at a time,
    so a list of 80 MB (500 MB unpacked) needs little memory. With `needles`,
    only entries whose text has one of them are read closer."""
    url = ARCHIVE.format(y=day.year, m=day.month, d=day.day)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    channel, topic, rest = "", "", ""
    with urllib.request.urlopen(request, timeout=60) as response, unpacked(response) as text:
        while True:
            chunk = text.read(4 << 20)
            if not chunk:
                break
            pieces = (rest + chunk).split('"X":')
            rest = pieces.pop()
            for piece in pieces:
                # the station and topic are only written when they change:
                # kept for the entries after
                head = piece[:200]
                if head.startswith('["'):
                    first = head[2:head.find('"', 2)] if '"' in head[2:] else ""
                    channel = first or channel
                low = piece.lower() if needles else ""
                if needles and not any(n in low for n in needles):
                    if head.startswith('["",') or not head.startswith('["'):
                        continue
                    try:  # the topic may change here: read just enough for it
                        x = json.loads(piece.rstrip().rstrip(",").rstrip("}"))
                        topic = x[1] or topic
                    except ValueError:
                        pass
                    continue
                piece = piece.rstrip().rstrip(",").rstrip("}")
                if not piece.startswith("["):
                    continue
                try:
                    x = json.loads(piece)
                except ValueError:
                    continue
                if len(x) < 10:
                    continue
                b = _broadcast(x, channel, topic)
                channel, topic = b["channel"], b["topic"]
                yield b
    piece = rest.rstrip().rstrip("}")
    if piece.startswith("["):
        try:
            x = json.loads(piece)
            yield _broadcast(x, channel, topic)
        except (ValueError, IndexError):
            pass


def search_archive(wanted, day, length=None, wanted_years=()):
    """Broadcasts in the archive's lists after `day` that share words with
    `wanted`: [(score, broadcast)], best first."""
    needles = sorted(wanted, key=len, reverse=True)[:3]
    found, seen = [], set()
    for after in AFTER_DAYS:
        list_day = day + datetime.timedelta(days=after)
        if list_day < FIRST_ARCHIVE or list_day > datetime.date.today():
            continue
        log(f"looking in the archive's list of {list_day.isoformat()} …")
        try:
            for b in archive_list(list_day, needles):
                text = f"{b['title']} {b['topic']}".lower()
                if not any(n in text for n in needles):
                    continue
                key = (b["channel"], b["title"], b["date"])
                if key in seen:
                    continue
                seen.add(key)
                s = score(b, wanted, length, wanted_years, day)
                if s > 0:
                    found.append((s, b))
        except Exception as exc:  # noqa: BLE001 — that day's list is missing: the next one
            log(f"the list of {list_day.isoformat()} couldn't be read ({exc})")
            continue
        if after >= 7 and found and max(s for s, _ in found) >= 3:
            break  # the lists a day and a week after: both; a month after only if nothing yet
    return sorted(found, key=lambda f: -f[0])


def score(b, wanted, length=None, wanted_years=(), day=None):
    """How well a broadcast fits: shared words, the year, the date, the
    length."""
    theirs = words(f"{b.get('title')} {b.get('topic')}")
    shared = len(wanted & theirs)
    # enough in common: two words, and half the words of the shorter name
    # ("Christmas" and "Concert" alone don't make "Jingle bells! – Christmas
    # on ARTE Concert" the crabs of Christmas Island)
    if shared < min(2, len(wanted)) or shared < 0.5 * min(len(wanted), len(theirs) or 1):
        return 0
    # a broadcast less than half as long as the file: a trailer, a clip, an
    # interview about it — not the recording
    if length and b.get("duration") and b["duration"] < 0.45 * length:
        return 0
    # another year in its title: another concert of the series
    title_years = years(f"{b.get('title')} {b.get('topic')}")
    if wanted_years and title_years and not (wanted_years & title_years):
        return 0
    s = shared + (1 if words(b.get("channel")) & wanted else 0)  # the station named in the file name
    when = None
    if b.get("timestamp"):
        when = datetime.datetime.fromtimestamp(int(b["timestamp"]), datetime.timezone.utc).date()
    elif b.get("date"):
        when = date_in(b["date"])
    their_years = years(f"{b.get('title')} {b.get('topic')}") | ({when.year} if when else set())
    if wanted_years:
        s += 2 if wanted_years & their_years else -2
    if day and when:
        s += 2 if abs((when - day).days) <= 2 else 0
    if length and b.get("duration"):
        off = abs(b["duration"] - length) / length
        s += 3 if off < 0.03 else 1 if off < 0.1 else 0
    return s


# -- modes -----------------------------------------------------------------------------------------------

def by_name(text):
    out = [scene_of(b, words(text)) for b in search_online(text, 15)]
    day = date_in(text)
    if day:
        wanted = words(re.sub(r"\d", " ", text))
        out += [scene_of(b, wanted) for _, b in search_archive(wanted, day, wanted_years={day.year})[:15]]
    return out


def by_fragment(data):
    title = data.get("title") or ""
    files, length, day = [], None, date_in(data.get("date") or "")
    if data.get("id"):
        try:
            found = stash("query($id: ID!) { findScene(id: $id) { title date files { path basename duration mod_time } } }",
                          {"id": data["id"]}).get("findScene") or {}
            files = found.get("files") or []
            title = title or found.get("title") or ""
            day = day or date_in(found.get("date") or "")
        except Exception as exc:  # noqa: BLE001 — Stash not reachable from here: the title alone
            log(f"couldn't ask Stash for the scene's file ({exc})")
    name = " ".join([title] + [os.path.splitext(f.get("basename") or "")[0] for f in files[:1]])
    wanted = words(re.sub(r"[._]+", " ", name))
    if not wanted:
        raise SystemExit("The scene has no title and no file name to look for.")
    wanted_years = years(name)
    length = next((f.get("duration") for f in files if f.get("duration")), None)
    if not day:
        day = date_in(name)
    if not day and wanted_years:
        # concerts on a fixed day: New Year's, New Year's Eve
        year = min(wanted_years)
        low = name.lower()
        if "neujahr" in low or "new year" in low:
            day = datetime.date(year, 1, 1)
        elif "silvester" in low or "new year's eve" in low:
            day = datetime.date(year, 12, 31)
    if not day and files and files[0].get("mod_time"):
        # the file's date: a recording is usually saved the day it aired
        day = date_in(files[0]["mod_time"][:10])
        # a New Year's Eve concert is saved on the 1st of January: the year
        # before counts too (January, February)
        if day and wanted_years and day.year not in wanted_years and not (day.year - 1 in wanted_years and day.month <= 2):
            day = None
    query = " ".join(sorted(wanted, key=len, reverse=True)[:4])
    best = sorted(((score(b, wanted, length, wanted_years, day), b) for b in search_online(query)),
                  key=lambda f: -f[0])
    if best and best[0][0] >= 3:
        log(f"found online: {best[0][1]['title']} ({best[0][1]['channel']})")
        return scene_of(best[0][1], wanted)
    if day:
        archived = search_archive(wanted, day, length, wanted_years)
        if archived and archived[0][0] >= 3:
            log(f"found in the archive: {archived[0][1]['title']} ({archived[0][1]['channel']}, {archived[0][1]['date']})")
            return scene_of(archived[0][1], wanted)
    hint = "" if day else " For the archive it needs a date: the scene's, one in its title or file name, or the file's."
    raise SystemExit(f"Nothing found for “{query}”.{hint}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "fragment"
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if mode == "name":
        print(json.dumps(by_name(data.get("name") or "")))
    elif mode == "query":
        print(json.dumps(data))  # the broadcast chosen from the search: all there already
    else:
        print(json.dumps(by_fragment(data)))


if __name__ == "__main__":
    # Stash reads the result from stdout: always JSON — "null" / [] when
    # there's none — and the reason in its log (stderr).
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            sys.stderr.write(f"MediathekView: {exc.code}\n")
            print("[]" if (sys.argv[1:2] == ["name"]) else "null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"MediathekView: {type(exc).__name__}: {exc}\n")
        print("[]" if (sys.argv[1:2] == ["name"]) else "null")
