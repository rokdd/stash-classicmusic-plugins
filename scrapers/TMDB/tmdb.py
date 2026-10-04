"""Stash scene scraper: films and TV episodes from The Movie Database
(themoviedb.org) — concert films, opera and ballet productions,
documentaries, and episodes of series.

What a scene gets: title, overview, release / air date, poster or still,
the production company or network as studio, the director, cast and crew
(composers, conductors, …) as performers, genres as tags, the TMDB page as
URL.

Run by Stash (see TMDB.yml) with one argument:
  url       stdin {"url": …}       themoviedb.org/movie/<id>, /tv/<id>,
                                   /tv/<id>/season/<n>/episode/<n>
  name      stdin {"name": …}      → up to 15 films and series ("… 2019" prefers
                                   that year)
  query     stdin one of those       → that one, in full
  fragment  stdin a scene            → the film that fits the scene: its URL, else
                                   its title (or its file's name) and year

Needs an API key (free: themoviedb.org → Settings → API; the "API key" or
the "API Read Access Token"), from the first of:
  - the environment: TMDB_API_KEY
  - config.json next to this script: {"api_key": "…", "language": "de-DE"}
  - Stash's plugin settings: "TMDB API key" in Markers as Chapters (read
    through Stash's API: STASH_URL, default http://localhost:9999;
    STASH_API_KEY if Stash has a login)
Language: TMDB_LANGUAGE / "language" (default de-DE; falls back to the
original for what isn't translated). Standard library only.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

API = "https://api.themoviedb.org/3"
IMAGES = "https://image.tmdb.org/t/p/original"
SITE = "https://www.themoviedb.org"
USER_AGENT = "StashTMDBScraper (https://github.com/rokdd/stash-classicmusic-plugins)"
HERE = os.path.dirname(os.path.abspath(__file__))
CREW_AS_PERFORMERS = {"Director", "Original Music Composer", "Music", "Composer", "Conductor", "Music Director",
                      "Musician", "Orchestrator", "Choreographer", "Opera Director", "Stage Director"}
LOG_INFO = "\x01i\x02"


def log(text):
    sys.stderr.write(f"{LOG_INFO}TMDB: {text}\n")


# -- settings ------------------------------------------------------------------------------------

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
    """(api key, language)."""
    config = {}
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        pass
    key = os.environ.get("TMDB_API_KEY") or config.get("api_key")
    language = os.environ.get("TMDB_LANGUAGE") or config.get("language")
    if not key:
        try:
            plugins = stash("query { configuration { plugins } }")["configuration"]["plugins"] or {}
        except Exception:  # noqa: BLE001
            plugins = {}
        for values in plugins.values():
            if isinstance(values, dict) and values.get("tmdbApiKey"):
                key = str(values["tmdbApiKey"]).strip()
                language = language or values.get("tmdbLanguage")
                break
    if not key:
        raise SystemExit("No TMDB API key — set it in Markers as Chapters' settings (TMDB API key), in config.json "
                         "next to the scraper, or as TMDB_API_KEY.")
    return key, (language or "de-DE")


KEY, LANGUAGE = None, None


def api(path, **params):
    params.setdefault("language", LANGUAGE)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if len(KEY) > 40:  # the read access token (v4 style)
        headers["Authorization"] = f"Bearer {KEY}"
    else:
        params["api_key"] = KEY
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


# -- TMDB → scene -----------------------------------------------------------------------------------

def people(credits, limit=25):
    names = []
    for c in (credits or {}).get("crew") or []:
        if c.get("job") in CREW_AS_PERFORMERS:
            names.append(c["name"])
    for c in ((credits or {}).get("cast") or [])[:limit]:
        names.append(c["name"])
    return list(dict.fromkeys(n for n in names if n))


def director_of(credits):
    return next((c["name"] for c in (credits or {}).get("crew") or [] if c.get("job") == "Director"), None)


def scene(title, overview, date, image, studio, credits, genres, url, original=None):
    out = {"title": title or original or ""}
    if overview:
        out["details"] = overview
    if date:
        out["date"] = date
    if image:
        out["image"] = IMAGES + image
    if studio:
        out["studio"] = {"name": studio}
    names = people(credits)
    if names:
        out["performers"] = [{"name": n} for n in names]
    director = director_of(credits)
    if director:
        out["director"] = director
    if genres:
        out["tags"] = [{"name": g["name"]} for g in genres if g.get("name")]
    out["urls"] = [url]
    return out


def movie(movie_id):
    m = api(f"/movie/{movie_id}", append_to_response="credits")
    if not m.get("overview") and LANGUAGE[:2] != (m.get("original_language") or ""):
        m["overview"] = api(f"/movie/{movie_id}", language="en-US").get("overview")
    studio = next((c["name"] for c in m.get("production_companies") or []), None)
    return scene(m.get("title"), m.get("overview"), m.get("release_date") or None, m.get("poster_path"),
                 studio, m.get("credits"), m.get("genres"), f"{SITE}/movie/{movie_id}", m.get("original_title"))


def tv(tv_id, season=None, episode=None):
    show = api(f"/tv/{tv_id}", append_to_response="credits")
    studio = next((n["name"] for n in show.get("networks") or []), None) or \
        next((c["name"] for c in show.get("production_companies") or []), None)
    if season is None or episode is None:
        return scene(show.get("name"), show.get("overview"), show.get("first_air_date") or None, show.get("poster_path"),
                     studio, show.get("credits"), show.get("genres"), f"{SITE}/tv/{tv_id}", show.get("original_name"))
    e = api(f"/tv/{tv_id}/season/{season}/episode/{episode}", append_to_response="credits")
    credits = e.get("credits") or {}
    credits = {"cast": (credits.get("cast") or []) + (credits.get("guest_stars") or []) + (e.get("guest_stars") or []),
               "crew": (credits.get("crew") or []) + (e.get("crew") or [])}
    title = f"{show.get('name')} – S{int(season):02d}E{int(episode):02d} {e.get('name') or ''}".strip()
    out = scene(title, e.get("overview") or show.get("overview"), e.get("air_date") or None,
                e.get("still_path") or show.get("poster_path"), studio, credits, show.get("genres"),
                f"{SITE}/tv/{tv_id}/season/{season}/episode/{episode}")
    if e.get("episode_number") is not None:
        out["code"] = f"S{int(season):02d}E{int(episode):02d}"
    return out


def by_url(url):
    m = re.search(r"themoviedb\.org/(?:[a-z]{2}(?:-[A-Z]{2})?/)?(movie|tv)/(\d+)(?:[^/]*)(?:/season/(\d+)/episode/(\d+))?", url)
    if not m:
        raise SystemExit(f"Not a TMDB film or series URL: {url}")
    kind, tmdb_id, season, episode = m.groups()
    return movie(tmdb_id) if kind == "movie" else tv(tmdb_id, season, episode)


# -- searching ------------------------------------------------------------------------------------------

def split_year(text):
    m = re.search(r"(?<!\d)((?:19|20)\d\d)(?!\d)", text or "")
    year = int(m.group(1)) if m else None
    rest = re.sub(r"(?<!\d)(?:19|20)\d\d(?!\d)", " ", text or "") if year else (text or "")
    return re.sub(r"\s+", " ", rest).strip(), year


def search(text):
    """[(kind, id, title, year, overview, poster)] — films and series."""
    query, year = split_year(text)
    found = api("/search/multi", query=query, include_adult="false").get("results") or []
    out = []
    for r in found:
        kind = r.get("media_type")
        if kind not in ("movie", "tv"):
            continue
        date = r.get("release_date") or r.get("first_air_date") or ""
        out.append((kind, r["id"], r.get("title") or r.get("name") or "", int(date[:4]) if date[:4].isdigit() else None,
                    r.get("overview") or "", r.get("poster_path"), date))
    if year:  # that year first, then the nearest
        out.sort(key=lambda r: abs((r[3] or 0) - year) if r[3] else 99)
    return out


def by_name(text):
    out = []
    for kind, tmdb_id, title, year, overview, poster, date in search(text)[:15]:
        item = {"title": f"{title} ({year})" if year else title, "urls": [f"{SITE}/{kind}/{tmdb_id}"]}
        if overview:
            item["details"] = overview
        if date:
            item["date"] = date
        if poster:
            item["image"] = IMAGES + poster
        out.append(item)
    return out


def by_fragment(data):
    for url in data.get("urls") or ([data["url"]] if data.get("url") else []):
        if "themoviedb.org" in url:
            return by_url(url)
    name = data.get("title") or ""
    if not name and data.get("id"):
        try:
            files = (stash("query($id: ID!) { findScene(id: $id) { files { basename } } }", {"id": data["id"]})
                     .get("findScene") or {}).get("files") or []
            name = os.path.splitext(files[0]["basename"])[0] if files else ""
        except Exception as exc:  # noqa: BLE001
            log(f"couldn't ask Stash for the file's name ({exc})")
    name = re.sub(r"[._]+", " ", name)
    name = re.sub(r"\b(720p|1080p|2160p|4k|hdtv|web(-?dl)?|bluray|bdrip|dvdrip|x26[45]|h\.?26[45]|aac|ac3|hd)\b.*$", "", name, flags=re.I)
    if not name.strip():
        raise SystemExit("The scene has no TMDB URL, no title and no file name to look for.")
    if data.get("date") and not split_year(name)[1]:
        name += f" {data['date'][:4]}"
    results = search(name)
    if not results:
        raise SystemExit(f"Nothing on TMDB for “{name.strip()}”.")
    kind, tmdb_id = results[0][0], results[0][1]
    log(f"took {results[0][2]} ({results[0][3]}) — of {len(results)} found")
    return movie(tmdb_id) if kind == "movie" else tv(tmdb_id)


def main():
    global KEY, LANGUAGE
    mode = sys.argv[1] if len(sys.argv) > 1 else "fragment"
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    KEY, LANGUAGE = settings()
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
            sys.stderr.write(f"TMDB: {exc.code}\n")
            print("[]" if sys.argv[1:2] == ["name"] else "null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"TMDB: {type(exc).__name__}: {exc}\n")
        print("[]" if sys.argv[1:2] == ["name"] else "null")
