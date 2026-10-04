"""Stash scene scraper: series episodes and films from TheTVDB
(thetvdb.com) — concert series, recurring broadcasts (New Year's concerts,
festival seasons), documentaries.

What a scene gets: title (series – SxxEyy episode), overview, air date,
picture, the network or studio, the people (cast, guests, director …) as
performers, genres as tags, the TVDB page as URL. Titles and overviews in
the chosen language where TVDB has them, else the original.

Run by Stash (see TVDB.yml) with one argument:
  url       stdin {"url": …}       thetvdb.com/series/<slug>, /series/<slug>/episodes/<id>,
                                   /movies/<slug>
  name      stdin {"name": …}      → up to 15 series and films ("… 2019" prefers that year)
  query     stdin one of those       → that one, in full
  fragment  stdin a scene            → by its TVDB URL, else its title (or its file's
                                   name) and year; "S03E05" in it picks the episode

Needs an API key (thetvdb.com → Dashboard → API keys; a subscriber PIN if
the key is a user-supported one), from the first of:
  - the environment: TVDB_API_KEY (TVDB_PIN)
  - config.json next to this script: {"api_key": "…", "pin": "…", "language": "deu"}
  - Stash's plugin settings: "TVDB API key" in Markers as Chapters (read
    through Stash's API: STASH_URL, default http://localhost:9999;
    STASH_API_KEY if Stash has a login)
Language: three letters, TVDB_LANGUAGE / "language" (default deu).
Standard library only.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api4.thetvdb.com/v4"
SITE = "https://thetvdb.com"
USER_AGENT = "StashTVDBScraper (https://github.com/rokdd/stash-classicmusic-plugins)"
HERE = os.path.dirname(os.path.abspath(__file__))
PEOPLE_TYPES = {"Actor", "Guest Star", "Director", "Host", "Musical Guest", "Composer", "Creator"}
LOG_INFO = "\x01i\x02"


def log(text):
    sys.stderr.write(f"{LOG_INFO}TVDB: {text}\n")


# -- settings and requests ------------------------------------------------------------------------------

def stash(query, variables=None):
    base = os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("STASH_API_KEY"):
        headers["ApiKey"] = os.environ["STASH_API_KEY"]
    request = urllib.request.Request(f"{base}/graphql", data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8")).get("data") or {}


def settings():
    """(api key, pin, language)."""
    config = {}
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        pass
    key = os.environ.get("TVDB_API_KEY") or config.get("api_key")
    pin = os.environ.get("TVDB_PIN") or config.get("pin")
    language = os.environ.get("TVDB_LANGUAGE") or config.get("language")
    if not key:
        try:
            plugins = stash("query { configuration { plugins } }")["configuration"]["plugins"] or {}
        except Exception:  # noqa: BLE001
            plugins = {}
        for values in plugins.values():
            if isinstance(values, dict) and values.get("tvdbApiKey"):
                key = str(values["tvdbApiKey"]).strip()
                pin = pin or values.get("tvdbPin")
                language = language or values.get("tvdbLanguage")
                break
    if not key:
        raise SystemExit("No TVDB API key — set it in Markers as Chapters' settings (TVDB API key), in config.json "
                         "next to the scraper, or as TVDB_API_KEY.")
    return key, pin, (language or "deu")


TOKEN, LANGUAGE = None, "deu"


def request(path, body=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(f"{API}{path}", headers=headers, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8")).get("data")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"TVDB answered {exc.code} for {path}: {detail}") from exc


def login(key, pin):
    global TOKEN
    body = {"apikey": key}
    if pin:
        body["pin"] = str(pin)
    TOKEN = (request("/login", body) or {}).get("token")
    if not TOKEN:
        raise SystemExit("TVDB didn't accept the API key.")


def translated(kind, tvdb_id, item):
    """Name and overview in the chosen language, where TVDB has them."""
    t = request(f"/{kind}/{tvdb_id}/translations/{LANGUAGE}") or {}
    return t.get("name") or item.get("name"), t.get("overview") or item.get("overview")


# -- TVDB → scene ----------------------------------------------------------------------------------------

def image(url):
    if not url:
        return None
    return url if url.startswith("http") else f"https://artworks.thetvdb.com{url}"


def scene(title, overview, date, picture, studio, characters, genres, url, code=None, director=None):
    out = {"title": title or ""}
    if overview:
        out["details"] = overview
    if date:
        out["date"] = date[:10]
    if image(picture):
        out["image"] = image(picture)
    if studio:
        out["studio"] = {"name": studio}
    names = list(dict.fromkeys(c.get("personName") for c in characters or []
                               if c.get("personName") and c.get("peopleType") in PEOPLE_TYPES))
    if names:
        out["performers"] = [{"name": n} for n in names[:30]]
    director = director or next((c.get("personName") for c in characters or [] if c.get("peopleType") == "Director"), None)
    if director:
        out["director"] = director
    if genres:
        out["tags"] = [{"name": g["name"]} for g in genres if g.get("name")]
    out["urls"] = [url]
    if code:
        out["code"] = code
    return out


def network(series):
    for key in ("originalNetwork", "latestNetwork"):
        if (series.get(key) or {}).get("name"):
            return series[key]["name"]
    return next((c.get("name") for c in series.get("companies") or [] if c.get("name")), None)


def series_scene(series_id):
    s = request(f"/series/{series_id}/extended") or {}  # not short: the people too
    name, overview = translated("series", series_id, s)
    return scene(name, overview, s.get("firstAired"), s.get("image"), network(s), s.get("characters"),
                 s.get("genres"), f"{SITE}/series/{s.get('slug') or series_id}")


def episode_scene(episode_id):
    e = request(f"/episodes/{episode_id}/extended") or {}
    s = (request(f"/series/{e['seriesId']}/extended?short=true") or {}) if e.get("seriesId") else {}
    series_name = translated("series", e["seriesId"], s)[0] if s else ""
    name, overview = translated("episodes", episode_id, e)
    code = f"S{int(e.get('seasonNumber') or 0):02d}E{int(e.get('number') or 0):02d}"
    title = " – ".join(x for x in (series_name, f"{code} {name or ''}".strip()) if x)
    return scene(title, overview or (s.get("overview") if s else None), e.get("aired"), e.get("image") or s.get("image"),
                 network(s) if s else None, e.get("characters"), s.get("genres") if s else None,
                 f"{SITE}/series/{s.get('slug') or e.get('seriesId')}/episodes/{episode_id}", code)


def movie_scene(movie_id):
    m = request(f"/movies/{movie_id}/extended?short=true") or {}
    name, overview = translated("movies", movie_id, m)
    date = (m.get("first_release") or {}).get("date") or (m.get("releases") or [{}])[0].get("date")
    studio = next((c.get("name") for c in m.get("studios") or [] if c.get("name")), None)
    return scene(name, overview, date, m.get("image"), studio, m.get("characters"), m.get("genres"),
                 f"{SITE}/movies/{m.get('slug') or movie_id}")


def by_url(url):
    m = re.search(r"thetvdb\.com/(?:dereferrer/)?(series|movies?)/([^/?#]+)(?:/episodes/(\d+))?", url)
    if not m:
        raise SystemExit(f"Not a TVDB series, episode or film URL: {url}")
    kind, slug, episode = m.groups()
    if episode:
        return episode_scene(episode)
    kind = "series" if kind == "series" else "movies"
    tvdb_id = slug if slug.isdigit() else (request(f"/{kind}/slug/{slug}") or {}).get("id")
    if not tvdb_id:
        raise SystemExit(f"TVDB doesn't know {url}")
    return series_scene(tvdb_id) if kind == "series" else movie_scene(tvdb_id)


# -- searching -------------------------------------------------------------------------------------------

def split(text):
    """(words, year, season, episode) from a title or file name."""
    m = re.search(r"\bS(\d{1,4})\s*E(\d{1,3})\b", text or "", re.I)
    season, episode = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    text = re.sub(r"\bS\d{1,4}\s*E\d{1,3}\b.*$", "", text or "", flags=re.I) if m else (text or "")
    y = re.search(r"(?<!\d)((?:19|20)\d\d)(?!\d)", text)
    year = int(y.group(1)) if y else None
    text = re.sub(r"(?<!\d)(?:19|20)\d\d(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip(), year, season, episode


def search(text):
    query, year, _, _ = split(text)
    params = {"query": query, "limit": 30}
    found = request(f"/search?{urllib.parse.urlencode(params)}") or []
    found = [r for r in found if r.get("type") in ("series", "movie")]
    if year:
        found.sort(key=lambda r: abs(int(r.get("year") or 0) - year) if str(r.get("year") or "").isdigit() else 99)
    return found


def by_name(text):
    out = []
    for r in search(text)[:15]:
        kind = "series" if r["type"] == "series" else "movies"
        name = (r.get("translations") or {}).get(LANGUAGE) or r.get("name") or ""
        item = {"title": f"{name} ({r['year']})" if r.get("year") else name,
                "urls": [f"{SITE}/{kind}/{r.get('slug') or r.get('tvdb_id')}"]}
        overview = (r.get("overviews") or {}).get(LANGUAGE) or r.get("overview")
        if overview:
            item["details"] = overview
        if r.get("image_url"):
            item["image"] = r["image_url"]
        out.append(item)
    return out


def by_fragment(data):
    for url in data.get("urls") or ([data["url"]] if data.get("url") else []):
        if "thetvdb.com" in url:
            return by_url(url)
    name = data.get("title") or ""
    if data.get("id"):
        try:
            files = (stash("query($id: ID!) { findScene(id: $id) { files { basename } } }", {"id": data["id"]})
                     .get("findScene") or {}).get("files") or []
            base = os.path.splitext(files[0]["basename"])[0] if files else ""
            if not name or (re.search(r"\bS\d{1,4}\s*E\d{1,3}\b", base, re.I) and not re.search(r"\bS\d{1,4}\s*E\d{1,3}\b", name, re.I)):
                name = f"{name} {base}".strip() if name else base
        except Exception as exc:  # noqa: BLE001
            log(f"couldn't ask Stash for the file's name ({exc})")
    name = re.sub(r"[._]+", " ", name)
    if not name.strip():
        raise SystemExit("The scene has no TVDB URL, no title and no file name to look for.")
    if data.get("date") and not split(name)[1]:
        name += f" {data['date'][:4]}"
    results = search(name)
    if not results:
        raise SystemExit(f"Nothing on TVDB for “{split(name)[0]}”.")
    best = results[0]
    log(f"took {best.get('name')} ({best.get('year')}) — of {len(results)} found")
    tvdb_id = best.get("tvdb_id") or str(best.get("id", "")).split("-")[-1]
    if best["type"] == "movie":
        return movie_scene(tvdb_id)
    _, _, season, episode = split(name)
    if season is not None:
        episodes = (request(f"/series/{tvdb_id}/episodes/default?season={season}&episodeNumber={episode}") or {}).get("episodes") or []
        if episodes:
            return episode_scene(episodes[0]["id"])
    return series_scene(tvdb_id)


def main():
    global LANGUAGE
    mode = sys.argv[1] if len(sys.argv) > 1 else "fragment"
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    key, pin, LANGUAGE = settings()
    login(key, pin)
    if mode == "url":
        result = by_url(data.get("url") or "")
    elif mode == "name":
        result = by_name(data.get("name") or "")
    elif mode == "query":
        urls = data.get("urls") or ([data["url"]] if data.get("url") else [])
        result = by_url(urls[0]) if urls else None
    else:
        result = by_fragment(data)
    print(json.dumps(result))


if __name__ == "__main__":
    # Stash reads the result from stdout: always JSON — null / [] when there's
    # none — and the reason in its log (stderr).
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            sys.stderr.write(f"TVDB: {exc.code}\n")
            print("[]" if sys.argv[1:2] == ["name"] else "null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"TVDB: {type(exc).__name__}: {exc}\n")
        print("[]" if sys.argv[1:2] == ["name"] else "null")
