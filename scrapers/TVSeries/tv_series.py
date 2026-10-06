"""Stash scraper: the series a recording belongs to, from Wikipedia and
Wikidata — a TV series ("Sternstunde Musik"), a recurring concert ("Neujahrs-
konzert der Wiener Philharmoniker", "Silvesterkonzert …"), a festival or
concert series ("BBC Proms", "Lucerne Festival").

For a scene: the scene goes into a group named after the series — its
Wikipedia introduction as synopsis, its picture, the article as URL — and
the series' genres (Wikidata) become tags. For a group (its Wikipedia URL):
the group's details.

How it finds the series, and when it doesn't take one:
  - the scene's title or file name (without years, "720p" and the like),
    its runs of words tried as article titles in the German and English
    Wikipedia ("Last Night of the Proms" → "Proms", "Lucerne Festival") —
    the longest run that leads to an article wins (the most particular:
    "Neujahrskonzert der Wiener Philharmoniker" over "Wiener Philharmoniker");
  - then Wikipedia's search, an article counting only if all the words of
    its title are in the scene's name;
  - and only if Wikidata says it's a series, programme, recurring event,
    festival or concert series — not an orchestra, a person, a place.

Run by Stash (see TVSeries.yml) with one argument:
  fragment  stdin a scene            → the scene with its series as group
  name      stdin {"name": …}        → up to 10 series found by those words
  query     stdin one of those       → that one
  group     stdin {"url": …}         → a group from a Wikipedia article

Standard library only. The scene's file name is read through Stash's API
on this machine (STASH_URL, default http://localhost:9999; STASH_API_KEY if
Stash has a login).
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "StashTVSeriesScraper/1.0 (https://github.com/rokdd/stash-classicmusic-plugins)"
LANGUAGES = ("de", "en")
# what Wikidata calls things that are a series (P31's English label, a part of it)
SERIES_WORDS = ("series", "event", "festival", "programme", "program", "show", "broadcast", "concert", "special",
                "competition", "season")
NOT_SERIES = ("orchestra", "human", "ensemble", "city", "building", "list", "disambiguation", "band", "choir", "venue")
STOP = {"der", "die", "das", "des", "dem", "den", "und", "the", "and", "of", "in", "im", "mit", "with", "von", "a", "an",
        "de", "la", "le", "et", "mp4", "mkv", "m4v", "avi", "mpg", "vdr", "ts", "hd", "720p", "1080p", "hdtv", "x264"}
SMALL = {"of", "the", "and", "in", "on", "at", "for", "a", "an", "der", "die", "das", "des", "dem", "den", "und", "von",
         "im", "am", "zum", "zur", "mit", "aus", "auf", "de", "la", "le", "et", "du", "di"}
LOG_INFO = "\x01i\x02"


def log(text):
    sys.stderr.write(f"{LOG_INFO}TV series: {text}\n")


def get(url, tries=3):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt + 1 < tries:  # too many requests: wait as told
                time.sleep(min(30, int(exc.headers.get("Retry-After") or 5)))
                continue
            raise
    return {}


def api(lang, **params):
    params.update(format="json", formatversion="2")
    return get(f"https://{lang}.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}")


def stash(query, variables):
    base = os.environ.get("STASH_URL", "http://localhost:9999").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if os.environ.get("STASH_API_KEY"):
        headers["ApiKey"] = os.environ["STASH_API_KEY"]
    request = urllib.request.Request(f"{base}/graphql", data=json.dumps({"query": query, "variables": variables}).encode(),
                                     headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8")).get("data") or {}


def words(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in STOP and not re.fullmatch(r"\d+p?", w)]


def clean_name(text):
    """A title or file name as words to look for: no extension, years,
    technical bits."""
    text = re.sub(r"\.[a-z0-9]{2,4}$", "", text or "", flags=re.I)
    text = re.sub(r"[._]+", " ", text)
    text = re.sub(r"\b(19|20)\d\d\b|\b\d{3,4}p\b|\b(hdtv|web|x26[45]|h26[45]|aac|ac3|bbc fassung)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" -–")


# -- Wikidata --------------------------------------------------------------------------------------

def entities(ids, lang):
    ids = [i for i in dict.fromkeys(ids) if i]
    out = {}
    for start in range(0, len(ids), 40):
        data = get("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(ids[start:start + 40]), "props": "labels|claims|sitelinks",
             "languages": f"{lang}|en", "format": "json"}))
        out.update(data.get("entities") or {})
    return out


def claim_ids(entity, prop):
    return [c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") for c in (entity.get("claims") or {}).get(prop, [])]


def claim_string(entity, prop):
    for c in (entity.get("claims") or {}).get(prop, []):
        value = c["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(value, str):
            return value
    return None


def label(entity, lang):
    labels = entity.get("labels") or {}
    return (labels.get(lang) or labels.get("en") or {}).get("value")


def is_series(kinds):
    names = " ".join(k.lower() for k in kinds)
    return any(w in names for w in SERIES_WORDS) and not any(w in names for w in NOT_SERIES)


# -- the series -------------------------------------------------------------------------------------

def spans(name, longest=7, shortest=2):
    """The name's runs of words, longest first: the titles an article might
    have ("Last Night of the Proms", "Lucerne Festival")."""
    tokens = [t for t in re.split(r"[\s\-–!?,;:()]+", clean_name(name)) if t]
    out = []
    for n in range(min(longest, len(tokens)), shortest - 1, -1):
        for i in range(len(tokens) - n + 1):
            run = tokens[i:i + n]
            if run[0].lower() in STOP or run[-1].lower() in STOP:
                continue  # "der Wiener" isn't a title
            title = " ".join(run)
            # titles are case-sensitive after their first letter: "Last Night
            # Of The Proms" is tried as "Last Night of the Proms" too
            small = " ".join(w.lower() if i and w.lower() in SMALL else w for i, w in enumerate(run))
            for t in (title, small):
                t = t[:1].upper() + t[1:]
                if t not in out:
                    out.append(t)
    return out[:150]


def candidates(name):
    """[(lang, article title)] — the name's runs of words that are an
    article's title (or lead to one), the longest first; then what
    Wikipedia's search finds whose title words are all in the name."""
    wanted = set(words(name))
    found, seen = [], set()
    tries = spans(name)
    for lang in LANGUAGES:
        pages, came_from = [], {}
        for start in range(0, len(tries), 50):  # 50 titles per request at most
            try:
                q = api(lang, action="query", titles="|".join(tries[start:start + 50]), redirects=1).get("query", {})
            except Exception as exc:  # noqa: BLE001
                log(f"Wikipedia ({lang}) didn't answer: {exc}")
                break
            pages += q.get("pages", [])
            # which of the name's runs led to a page (through a redirect):
            # its length decides, not the length of where it led
            for step in (q.get("normalized") or []) + (q.get("redirects") or []):
                came_from[step["to"]] = max(came_from.get(step["to"], ""), came_from.get(step["from"], step["from"]),
                                            key=lambda t: len(words(t)))
        for page in pages:
            if "missing" not in page and "invalid" not in page and (lang, page["title"]) not in seen:
                seen.add((lang, page["title"]))
                matched = max(page["title"], came_from.get(page["title"], ""), key=lambda t: len(words(t)))
                found.append((lang, page["title"], len(words(matched))))
    query = clean_name(name)
    for lang in LANGUAGES:
        try:
            hits = api(lang, action="query", list="search", srsearch=query, srlimit=10).get("query", {}).get("search", [])
        except Exception:  # noqa: BLE001
            continue
        for h in hits:
            own = set(words(re.sub(r"\s*\(.*?\)\s*", " ", h["title"])))  # "(Fernsehserie)" doesn't count
            if own and own <= wanted and (lang, h["title"]) not in seen:
                seen.add((lang, h["title"]))
                found.append((lang, h["title"], len(own) - 0.5))  # behind an exact title of the same length
    found.sort(key=lambda f: -f[2])
    return [(lang, title) for lang, title, _ in found]


def series(lang, title):
    """The series' details from its article, or None if it isn't a series."""
    pages = api(lang, action="query", titles=title, prop="pageprops|extracts|info", exintro=1, explaintext=1,
                inprop="url", redirects=1).get("query", {}).get("pages", [])
    if not pages or "missing" in pages[0]:
        return None
    page = pages[0]
    qid = (page.get("pageprops") or {}).get("wikibase_item")
    if not qid:
        return None
    item = entities([qid], lang).get(qid) or {}
    kinds_ids = claim_ids(item, "P31")
    genre_ids = claim_ids(item, "P136")
    labelled = entities(kinds_ids + genre_ids + claim_ids(item, "P449"), lang)
    kinds = [label(labelled.get(k, {}), "en") or "" for k in kinds_ids]
    if not is_series(kinds):
        log(f"“{page['title']}” is {', '.join(k for k in kinds if k) or 'something else'} — not a series")
        return None
    image = claim_string(item, "P18") or claim_string(item, "P154")
    return {
        "name": page["title"],
        "synopsis": (page.get("extract") or "").strip(),
        "url": page.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(page['title'])}",
        "image": f"https://commons.wikimedia.org/wiki/Special:FilePath/{urllib.parse.quote(image)}?width=800" if image else None,
        "genres": [g for g in (label(labelled.get(i, {}), lang) for i in genre_ids) if g],
        "broadcaster": next((label(labelled.get(i, {}), lang) for i in claim_ids(item, "P449")), None),
        "kinds": [k for k in kinds if k],
    }


def find(name):
    for lang, title in candidates(name):
        found = series(lang, title)
        if found:
            log(f"found “{found['name']}” ({', '.join(found['kinds'])})")
            return found
    return None


def group_of(s):
    g = {"name": s["name"], "urls": [s["url"]]}
    if s.get("synopsis"):
        g["synopsis"] = s["synopsis"]
    if s.get("image"):
        g["front_image"] = s["image"]
    if s.get("genres"):
        g["tags"] = [{"name": t} for t in s["genres"]]
    if s.get("broadcaster"):
        g["studio"] = {"name": s["broadcaster"]}
    return g


# -- modes -------------------------------------------------------------------------------------------

def by_fragment(data):
    name = data.get("title") or ""
    if data.get("id"):
        try:
            found = stash("query($id: ID!) { findScene(id: $id) { title files { basename } } }", {"id": data["id"]}).get("findScene") or {}
            files = found.get("files") or []
            name = " ".join(x for x in [name or found.get("title") or "", files[0]["basename"] if files else ""] if x)
        except Exception as exc:  # noqa: BLE001
            log(f"couldn't ask Stash for the file's name ({exc})")
    if not name.strip():
        raise SystemExit("The scene has no title and no file name to look for.")
    s = find(name)
    if not s:
        raise SystemExit(f"No series on Wikipedia for “{clean_name(name)}” (only series, programmes, recurring "
                         "concerts and festivals count, and their name has to be in the scene's).")
    out = {"groups": [group_of(s)]}
    if s.get("genres"):
        out["tags"] = [{"name": t} for t in s["genres"]]
    return out


def by_name(text):
    out = []
    for lang, title in candidates(text)[:10] or [(lang, h["title"]) for lang in LANGUAGES
                                                 for h in api(lang, action="query", list="search", srsearch=text,
                                                              srlimit=5).get("query", {}).get("search", [])]:
        s = series(lang, title)
        if s:
            out.append({"title": s["name"], "details": s["synopsis"][:500], "urls": [s["url"]],
                        "groups": [group_of(s)], "tags": [{"name": t} for t in s["genres"]]})
    return out


def by_group_url(url):
    m = re.search(r"//([a-z]{2,3})\.(?:m\.)?wikipedia\.org/wiki/([^?#]+)", url)
    if not m:
        raise SystemExit(f"Not a Wikipedia article: {url}")
    s = series(m.group(1), urllib.parse.unquote(m.group(2)).replace("_", " "))
    if not s:
        raise SystemExit("That article isn't about a series.")
    return group_of(s)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "fragment"
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if mode == "name":
        result = by_name(data.get("name") or "")
    elif mode == "query":
        result = data
    elif mode == "group":
        result = by_group_url(data.get("url") or "")
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
            sys.stderr.write(f"TV series: {exc.code}\n")
            print("[]" if sys.argv[1:2] == ["name"] else "null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"TV series: {type(exc).__name__}: {exc}\n")
        print("[]" if sys.argv[1:2] == ["name"] else "null")
