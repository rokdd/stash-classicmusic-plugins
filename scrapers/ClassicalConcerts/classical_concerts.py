"""Stash scene scraper for concert recordings from broadcasters.

ARTE (ARTE Concert), ORF ON, ARD Mediathek, ZDF, 3sat and BBC: title,
programme text, concert date, cover, the broadcaster as studio, and
orchestra, conductor, soloists and composers as performers. Standard
library only.

Run by Stash (see ClassicalConcerts.yml) with one argument:
  url       stdin {"url": …}     → the scene at that URL
  fragment  stdin a scene          → the scene, by the first URL it has that
                                     one of the sources handles

Per source:
  ARTE      the player's data (title, subtitle, description, cover,
            chapters), and from the page itself the credits (orchestra,
            conductor, soloists, director) and the full description;
            composers from the chapter titles ("Composer - Work")
  ORF ON    ORF's API: title, description, date, cover, channel (ORF III …),
            the segments as the programme
  ARD       the Mediathek's API: title, programme text, broadcast date,
            cover, the broadcaster (hr, BR …)
  ZDF/3sat  the page's own data (schema.org VideoObject / Open Graph)
  BBC       the programme's data, and its "Music Played": composers, works,
            orchestra, conductor, soloists
Everywhere, performers are also read from the programme text — "Alain
Altinoglu, Dirigent", "Giorgi Gigashvili (Klavier)", "Dirigent: …",
orchestras and ensembles on a line of their own, composers as "Name:" —
and the date is the concert's when the text names one ("Alte Oper
Frankfurt, 24. November 2023"), else the broadcast date.
"""

import base64
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (StashClassicalConcertsScraper; https://github.com/rokdd/stash-classicmusic-plugins)"


# -- requests -------------------------------------------------------------------------

def fetch(url, accept="text/html,application/json"):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept,
                                                   "Accept-Language": "de,en;q=0.8"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def fetch_json(url):
    return json.loads(fetch(url, "application/json"))


# -- text -----------------------------------------------------------------------------

def plain(text):
    """HTML → text, paragraphs and line breaks kept."""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace(" ", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


MONTHS = {m: i for i, m in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"], 1)}
MONTHS.update({m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)})
MONTHS.update({"jänner": 1, "maerz": 3})
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))


def concert_date(text):
    """A date named in the text — "24. November 2023", "24 November 2023",
    "November 24, 2023" — as YYYY-MM-DD, or None."""
    for pattern, order in ((rf"\b(\d{{1,2}})\.?\s+({_MONTH})\s+(\d{{4}})\b", "dmy"),
                           (rf"\b({_MONTH})\s+(\d{{1,2}}),?\s+(\d{{4}})\b", "mdy")):
        m = re.search(pattern, text or "", re.I)
        if m:
            a, b, year = m.groups()
            day, month = (a, b) if order == "dmy" else (b, a)
            return f"{year}-{MONTHS[month.lower()]:02d}-{int(day):02d}"
    return None


def iso_date(value):
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value or "")
    return m.group(1) if m else None


# -- performers from text ----------------------------------------------------------------

ROLES = (r"Dirigent(?:in)?|Leitung|Musikalische Leitung|Klavier|Piano|Violine|Geige|Viola|Bratsche|Violoncello|Cello|"
         r"Kontrabass|Flöte|Oboe|Klarinette|Fagott|Horn|Trompete|Posaune|Tuba|Harfe|Orgel|Cembalo|Gitarre|Laute|"
         r"Sopran|Mezzosopran|Alt|Tenor|Bariton|Bassbariton|Bass|Countertenor|Schlagzeug|Percussion|Gesang|"
         r"Conductor|Violin|Soprano|Mezzo-soprano|Baritone|Bass-baritone|Organ|Harpsichord|Guitar|Flute|Clarinet|"
         r"Bassoon|Trumpet|Trombone|Harp|Voice|Solist(?:in)?|Soloist|Moderation|Presenter")
ROLE_RE = re.compile(rf"^(?:{ROLES})(?:\s|$|[,/)])", re.I)
# Ensembles — not works or concert series ("2. Sinfonie", "Sinfoniekonzert").
ENSEMBLE_RE = re.compile(r"orchester\b|orchestra\b|orchestre|orquesta|philharmoni(?:ker|c|e|a)\b|symphony\b|chor\b|choir\b|"
                         r"chorus\b|ensemble\b|quartett\b|quartet\b|quintett\b|quintet\b|trio\b|consort\b|kapelle\b|"
                         r"camerata\b|solisten\b|soloists\b|singers\b|sinfonietta\b", re.I)
PARTICLES = {"van", "von", "de", "der", "den", "di", "da", "du", "le", "la", "y", "del", "zu", "ten", "ter", "bin"}


def name_like(text):
    words = text.split()
    if not 2 <= len(words) <= 5 or re.search(r"\d|[.!?]$|[:;()\[\]]", text):
        return False
    return all(w[:1].isupper() or w.lower() in PARTICLES or w[:1] == "'" for w in words)


def ensemble_like(text):
    return bool(ENSEMBLE_RE.search(text)) and len(text.split()) <= 7 and not re.search(r"[.!?]$|\d|\bop\b", text)


def from_text(text):
    """(performers, composers) named in a programme text."""
    performers, composers = [], []
    for raw in re.split(r"\n|\s\|\s|;\s", text or ""):
        line = raw.strip(" •·-–—*\t")
        if not line or len(line) > 120:
            continue
        # "Johannes Brahms:" or "Johannes Brahms: 2. Sinfonie" — a composer
        m = re.match(r"^([^:]{3,60}):\s*(.*)$", line)
        if m and name_like(m.group(1)) and not ROLE_RE.match(m.group(1)):
            composers.append(m.group(1))
            continue
        # "Dirigent: Name" / "Klavier – Name"
        m = re.match(rf"^(?:{ROLES})\s*[:–-]\s*(.+)$", line, re.I)
        if m:
            performers += [n.strip() for n in re.split(r",| und | and ", m.group(1)) if name_like(n.strip()) or ensemble_like(n.strip())]
            continue
        # "Name, Dirigent" / "Name, Klavier"
        m = re.match(r"^(.+?),\s*(.+)$", line)
        if m and name_like(m.group(1)) and ROLE_RE.match(m.group(2)):
            performers.append(m.group(1))
            continue
        # "Name (Klavier)"
        m = re.match(r"^(.+?)\s*\((.+)\)$", line)
        if m and name_like(m.group(1)) and ROLE_RE.match(m.group(2)):
            performers.append(m.group(1))
            continue
        # an orchestra / ensemble on its own line: "hr-Sinfonieorchester – Frankfurt Radio Symphony"
        first = re.split(r"\s[–—-]\s|,\s", line)[0].strip()
        first = re.sub(r"\s*\(.*$", "", first).strip()  # "Vocalconsort Berlin (Einstudierung: …)"
        if ensemble_like(first):
            performers.append(first)
    return performers, composers


def unique(names):
    import unicodedata
    out, seen = [], set()
    for n in names:
        n = unicodedata.normalize("NFC", re.sub(r"\s+", " ", (n or "").strip(" .,;")))
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def scene(title, details="", date=None, image=None, studio=None, performers=(), urls=(), director=None, tags=()):
    out = {"title": title}
    if details:
        out["details"] = details
    if date:
        out["date"] = date
    if image:
        out["image"] = image
    if studio:
        out["studio"] = {"name": studio}
    if performers:
        out["performers"] = [{"name": p} for p in unique(performers)]
    if urls:
        out["urls"] = list(dict.fromkeys(urls))
    if director:
        out["director"] = director
    if tags:
        out["tags"] = [{"name": t} for t in unique(tags)]
    return out


# -- ARTE -----------------------------------------------------------------------------------

def arte(url):
    m = re.search(r"arte\.tv/(?P<lang>[a-z]{2})/videos/(?P<id>\d{6}-\d{3}-[A-Z])", url) or \
        re.search(r"(?P<id>\d{6}-\d{3}-[A-Z])", url)
    if not m:
        raise SystemExit(f"No ARTE programme id (like 132137-000-A) in {url}")
    lang = (m.groupdict().get("lang") or "de").lower()
    program = m.group("id")
    attrs = fetch_json(f"https://api.arte.tv/api/player/v2/config/{lang}/{program}")["data"]["attributes"]
    meta = attrs.get("metadata") or {}
    title = (meta.get("title") or "").strip()
    if meta.get("subtitle"):
        title = f"{title} – {meta['subtitle'].strip()}"
    image = ((meta.get("images") or [{}])[0].get("url") or "").replace("940x530", "1920x1080") or None
    chapters = [c.get("title") or "" for c in ((attrs.get("chapters") or {}).get("elements") or [])]

    # The page: credits and the full description (in its embedded data).
    credits, full = [], ""
    try:
        page = fetch(f"https://www.arte.tv/{lang}/videos/{program}/")
        rsc = "".join(json.loads('"' + c + '"') for c in
                      re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', page))
        decoder = json.JSONDecoder()
        for hit in re.finditer(r'"credits":\[', rsc):
            if program in rsc[max(0, hit.start() - 4000):hit.start() + 4000]:
                credits, _ = decoder.raw_decode(rsc, hit.end() - 1)
                ref = re.search(r'"fullDescription":"\$(\w+)"', rsc[hit.start():hit.start() + 4000]) or \
                    re.search(r'"fullDescription":"\$(\w+)"', rsc[max(0, hit.start() - 4000):hit.start()])
                if ref:
                    chunk = re.search(rf"(?:^|\n){ref.group(1)}:T([0-9a-f]+),", rsc)
                    if chunk:
                        start = len(rsc[:chunk.end()].encode("utf-8"))
                        full = rsc.encode("utf-8")[start:start + int(chunk.group(1), 16)].decode("utf-8", "replace")
                break
    except Exception:  # noqa: BLE001 — the player's data alone is still a scene
        pass

    details = plain(full) or (meta.get("description") or "").strip()
    performers, director, year = [], None, None
    for c in credits:
        code, values = (c.get("code") or "").upper(), c.get("values") or []
        if code in ("REA",):
            director = ", ".join(values)
        elif code == "PRODUCTION_YEAR":
            year = (values or [None])[0]
        elif code in ("PRD", "COUNTRY", "ORIGIN", "AUT", "SCE", "IMA", "MON", "SON", "PRO", "CRE", "DOC", "COP", "PRE"):
            continue
        else:
            performers += [re.sub(r"\s*\([^)]*\)\s*$", "", v).strip() for v in values]
    composers = []
    for t in chapters:  # "Composer - Work", "Orchestra : Composer - Work", "Composer, Work"
        rest = t.split(" : ", 1)[-1]
        name = re.split(r"\s+-\s+|,\s", rest, maxsplit=1)[0].strip()
        if name_like(name):
            composers.append(name)
    text_performers, text_composers = from_text(details)
    date = concert_date(details) or (year if year and re.fullmatch(r"\d{4}", year) else None)
    return scene(title, details, date, image, "ARTE",
                 composers + text_composers + performers + text_performers,
                 [f"https://www.arte.tv/{lang}/videos/{program}/"], director)


# -- ORF ON ----------------------------------------------------------------------------------

def orf(url):
    m = re.search(r"on\.orf\.at/video/(\d+)", url)
    episode = m.group(1) if m else None
    if not episode and "tvthek.orf.at" in url:
        numbers = re.findall(r"/(\d{5,10})(?=/|$|\?)", url)
        episode = numbers[1] if len(numbers) > 1 else (numbers[0] if numbers else None)
    if not episode:
        raise SystemExit(f"No ORF ON video id in {url}")
    encoded = base64.b64encode(f"3dSlfek03nsLKdj4Jsd{episode}".encode()).decode()
    data = fetch_json(f"https://api-tvthek.orf.at/api/v4.3/public/episode/encrypted/{encoded}")
    emb = data.get("_embedded") or {}
    title = (data.get("title") or data.get("headline") or "").strip()
    description = plain(data.get("description") or "")
    segments = sorted(emb.get("segments") or [], key=lambda s: s.get("position") or 0)
    seg_titles = [(s.get("title") or "").strip() for s in segments if s.get("title")]
    details = description
    if len(seg_titles) > 1:
        details = (details + "\n\n" if details else "") + "Programm:\n" + "\n".join(seg_titles)
    image = (((emb.get("image") or {}).get("public_urls") or {}).get("highlight_teaser") or {}).get("url")
    studio = (emb.get("channel") or {}).get("name") or "ORF"
    performers, composers = from_text(description)
    for t in seg_titles:  # "Composer: Work" / "Composer – Work"
        name = re.split(r":\s|\s[–-]\s", t, maxsplit=1)[0].strip()
        if name_like(name):
            composers.append(name)
    date = concert_date(description) or iso_date(data.get("date"))
    return scene(title, details, date, image, studio, composers + performers, [f"https://on.orf.at/video/{episode}"])


# -- ARD Mediathek ------------------------------------------------------------------------------

def ard(url):
    m = re.search(r"ardmediathek\.de/(?:[^?#]*/)?([A-Za-z0-9_-]{20,})", url)
    if not m:
        raise SystemExit(f"No ARD Mediathek video id in {url}")
    item = m.group(1)
    data = fetch_json(f"https://api.ardmediathek.de/page-gateway/pages/ard/item/{item}?embedded=true")
    w = (data.get("widgets") or [{}])[0]
    title = (w.get("title") or "").strip()
    synopsis = plain(w.get("synopsis") or "")
    image = ((w.get("image") or {}).get("src") or "").replace("{width}", "1920") or None
    studio = (w.get("publicationService") or {}).get("name") or "ARD"
    performers, composers = from_text(synopsis)
    date = concert_date(synopsis) or iso_date(w.get("broadcastedOn"))
    show = (w.get("show") or {}).get("title")
    tags = [show] if show and show.lower() not in title.lower() else []
    return scene(title, synopsis, date, image, studio, composers + performers, [url.split("?")[0]], tags=tags)


# -- ZDF, 3sat (and any page with schema.org / Open Graph data) ---------------------------------

def page_data(url, default_studio):
    page = fetch(url)
    video = {}
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(item, dict) and item.get("@type") in ("VideoObject", "TVEpisode", "Episode", "BroadcastEvent"):
                video = item
                break
        if video:
            break

    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', page)
        return html.unescape(m.group(1)) if m else ""

    title = html.unescape(video.get("name") or "") or meta("og:title")
    details = plain(html.unescape(video.get("description") or "")) or meta("og:description") or meta("description")
    thumb = video.get("thumbnailUrl")
    image = (thumb[0] if isinstance(thumb, list) else thumb) or meta("og:image") or None
    if image:
        image = html.unescape(image).replace("~768x432", "~1280x720")
    publisher = (video.get("publisher") or {}).get("name") if isinstance(video.get("publisher"), dict) else None
    studio = re.split(r"\s+-\s+", publisher)[0] if publisher else default_studio
    performers, composers = from_text(details)
    date = concert_date(details) or iso_date(video.get("uploadDate") or video.get("datePublished") or meta("article:published_time"))
    return scene(title, details, date, image, studio, composers + performers, [url.split("?")[0]])


# -- BBC ------------------------------------------------------------------------------------------

def bbc(url):
    m = re.search(r"bbc\.co\.uk/(?:programmes|iplayer/episode|sounds/play)/([a-z0-9]{8})", url)
    if not m:
        raise SystemExit(f"No BBC programme id in {url}")
    pid = m.group(1)
    p = fetch_json(f"https://www.bbc.co.uk/programmes/{pid}.json")["programme"]
    display = p.get("display_title") or {}
    title = " – ".join(x for x in (display.get("title"), display.get("subtitle")) if x) or p.get("title") or ""
    details = (p.get("long_synopsis") or p.get("medium_synopsis") or p.get("short_synopsis") or "").strip()
    image = f"https://ichef.bbci.co.uk/images/ic/1920x1080/{(p.get('image') or {}).get('pid')}.jpg" if (p.get("image") or {}).get("pid") else None
    studio = (((p.get("ownership") or {}).get("service") or {}).get("title")) or "BBC"
    performers, composers, played = [], [], []
    try:
        page = fetch(f"https://www.bbc.co.uk/programmes/{pid}")
        for track in re.findall(r'<div class="segment__track">(.*?)</div>', page, re.S):
            artist = re.search(r'<span class="artist">(.*?)</span>', track, re.S)
            work = re.search(r'<p class="no-margin">\s*<span>(.*?)</span>', track, re.S)
            composer = plain(artist.group(1)) if artist else ""
            if composer:
                composers.append(composer)
            if work:
                played.append(f"{composer} – {plain(work.group(1))}" if composer else plain(work.group(1)))
            rest = plain(re.sub(r"<ul.*?</ul>", "", re.sub(r"<h3.*?</h3>|<p class=\"no-margin\">.*?</p>", "", track, flags=re.S), flags=re.S))
            for role, names in re.findall(r"([A-Z][A-Za-z ]+):\s*([^:]+?)\.(?=\s+[A-Z][A-Za-z ]+:|\s*$)", rest):
                if role.strip().lower() in ("record label", "music arranger", "lyricist"):
                    continue
                performers += [n.strip() for n in re.split(r",| & | and ", names) if n.strip()]
    except Exception:  # noqa: BLE001
        pass
    if played:
        details = (details + "\n\n" if details else "") + "Music played:\n" + "\n".join(dict.fromkeys(played))
    date = concert_date(details) or iso_date(p.get("first_broadcast_date"))
    return scene(title, details, date, image, studio, composers + performers, [f"https://www.bbc.co.uk/programmes/{pid}"])


# -- medici.tv ----------------------------------------------------------------------------------------
#
# medici.tv's own data for a programme (the same its site loads,
# api.medici.tv/satie/edito/movie-file/<slug>/). Without a login it has the
# title, subtitle (often the cast: "Thomas Adès (conductor) — With …"),
# recording date, picture and duration; with one (a JSON saved from it, next
# to the video) also the cast, composers, director, festival and venue.

def medici_scene(data, url=None):
    title = (data.get("title") or "").strip()
    subtitle = (data.get("subtitle") or "").strip()
    if subtitle and "(" not in subtitle:  # an event ("Lucerne Festival 2014"), not a cast list
        title = f"{title} – {subtitle}"
    details = plain(data.get("synopsis") or "")
    if not details and "(" in subtitle:
        details = subtitle
    date = None
    rec = str(data.get("recording_date") or "")
    if re.match(r"\d{4}-\d{2}-\d{2}", rec):
        date = rec[:10]
    elif re.fullmatch(r"\d{4}", rec.strip()):
        date = rec.strip()
    date = date or iso_date(data.get("date_publish"))
    image = data.get("hero_picture") or data.get("picture")
    performers, director = [], None
    for group in data.get("casting") or data.get("longCasting") or []:
        for entry in group if isinstance(group, list) else [group]:
            name = ((entry or {}).get("artist") or {}).get("name")
            if name:
                performers.append(name)
    # The cast in the subtitle: "Calixto Bieito (stage director), Thomas Adès (conductor) — With Jacquelyn Stucker (Lucia), …"
    for part in re.split(r"\s+[—–]\s+|,\s+", subtitle):
        part = re.sub(r"^(with|mit|avec)\s+", "", part.strip(), flags=re.I)
        m = re.match(r"^(.+?)\s*\(([^)]*)\)$", part)
        if not m:
            continue
        name, role = m.group(1).strip(), m.group(2).lower()
        if "director" in role or "regie" in role or "mise en scène" in role:
            director = director or name
        elif name_like(name) or ensemble_like(name):
            performers.append(name)
    composers = list(data.get("composers") or [])
    for chapter in data.get("chapters") or []:
        composers += ((chapter or {}).get("work") or {}).get("composers") or []
    directors = [d.get("name") for d in data.get("directors") or [] if d.get("name")]
    director = directors[0] if directors else director
    tags = [e.get("name") for e in data.get("events") or [] if e.get("name")]
    tags += [p.get("name") for p in data.get("places") or [] if p.get("name")]
    page = url or (f"https://www.medici.tv{data['url']}" if data.get("url") else None)
    return scene(title, details, date, image, "medici.tv", composers + performers, [page] if page else [], director, tags)


def medici(url):
    m = re.search(r"//(edu\.)?(?:www\.)?medici\.tv/[a-z]{2}/[a-z-]+/([a-z0-9-]+)", url)
    if not m:
        raise SystemExit(f"No medici.tv programme in {url}")
    api = f"https://api.medici.tv/{'edu-' if m.group(1) else ''}satie/edito/movie-file/{m.group(2)}/"
    origin = "https://edu.medici.tv" if m.group(1) else "https://www.medici.tv"
    request = urllib.request.Request(api, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                   "Origin": origin, "Referer": origin + "/", "Device-Type": "web"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 410:
            raise SystemExit(f"medici.tv doesn't show {m.group(2)} any more (unpublished).")
        raise
    return medici_scene(data, url.split("?")[0])


def looks_like_medici(data):
    return isinstance(data, dict) and "slug" in data and ("casting" in data or "chapters" in data or "synopsis" in data)


# -- a JSON file next to the video ---------------------------------------------------------------------
#
# Stash passes the scene's id, not its file: the file is looked up through
# Stash's own API on this machine (STASH_URL, default http://localhost:9999;
# STASH_API_KEY if Stash has a login).

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


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _words(text):
    return {w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 2}


def json_beside(scene_id):
    """medici.tv's JSON next to the scene's video: named like it
    (<video>.medici.json, <video>.json), else the only one in its folder, else
    the one whose name or title shares the most words with the video's."""
    for video in scene_files(scene_id):
        stem = os.path.splitext(video)[0]
        for path in (stem + ".medici.json", stem + ".json", video + ".json"):
            data = _load_json(path) if os.path.isfile(path) else None
            if looks_like_medici(data):
                return medici_scene(data)
        folder = os.path.dirname(video)
        found = []
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".json"):
                data = _load_json(os.path.join(folder, name))
                if looks_like_medici(data):
                    found.append((name, data))
        if len(found) == 1:
            return medici_scene(found[0][1])
        video_words = _words(os.path.basename(stem))
        scored = sorted(((len(video_words & (_words(name) | _words(d.get("title")) | _words(d.get("slug")))), d)
                         for name, d in found), key=lambda x: -x[0])
        if scored and scored[0][0] >= 2 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return medici_scene(scored[0][1])
    return None


# -- Stash -------------------------------------------------------------------------------------------

SOURCES = [
    ("arte.tv", arte),
    ("orf.at", orf),
    ("ardmediathek.de", ard),
    ("3sat.de", lambda u: page_data(u, "3sat")),
    ("zdf.de", lambda u: page_data(u, "ZDF")),
    ("bbc.co.uk", bbc),
    ("medici.tv", medici),
]


def scrape(url):
    for domain, handler in SOURCES:
        if domain in url:
            return handler(url)
    return None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "url"
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    urls = [data["url"]] if data.get("url") else []
    if mode == "fragment":
        urls = list(data.get("urls") or []) + ([data["url"]] if data.get("url") else [])
    problems = []
    # Scrape with… on a scene: medici.tv's JSON next to the video first — it
    # has more than any page (cast, composers, chapters) — keeping the
    # scene's URLs.
    if mode == "fragment" and data.get("id"):
        try:
            result = json_beside(data["id"])
        except Exception as exc:  # noqa: BLE001 — Stash not reachable from here: just no file
            problems.append(f"couldn't look for a JSON file next to the video ({exc})")
            result = None
        if result:
            result["urls"] = list(dict.fromkeys((result.get("urls") or []) + list(data.get("urls") or [])))
            print(json.dumps(result))
            return
    # Then the URLs, one after the other: one that fails (e.g. a programme
    # medici.tv doesn't show any more) doesn't stop the next.
    for url in urls:
        try:
            result = scrape(url)
        except SystemExit as exc:
            problems.append(f"{url}: {exc.code}")
            continue
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{url}: {type(exc).__name__}: {exc}")
            continue
        if result:
            print(json.dumps(result))
            return
    if problems:
        raise SystemExit("Nothing found — " + "; ".join(problems))
    raise SystemExit("No URL of ARTE, ORF ON, ARD Mediathek, ZDF, 3sat, BBC or medici.tv on this scene, "
                     "and no medici.tv JSON next to its video.")


if __name__ == "__main__":
    # Stash reads the result from stdout: always give it JSON — "null" (no
    # result) when there's none — and the reason in its log (stderr).
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            sys.stderr.write(f"Classical Concerts: {exc.code}\n")
            print("null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Classical Concerts: {type(exc).__name__}: {exc}\n")
        print("null")
