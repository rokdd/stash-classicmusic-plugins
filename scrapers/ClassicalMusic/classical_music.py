"""Stash performer scraper for a classical music library.

Composers, conductors, soloists, singers, orchestras and ensembles, from
Wikidata — with the Wikipedia introduction as details and, for composers,
the epoch from Open Opus (openopus.org). Standard library only.

Run by Stash (see ClassicalMusic.yml) with one argument:
  search    stdin {"name": …}            → a list of matching performers
  fragment  stdin a performer (a search result, or the performer's own
            fields: its Wikidata / Wikipedia / MusicBrainz URL, else its name)
                                         → the performer, filled in
  url       stdin {"url": …}             → the performer at that URL
            (wikidata.org/wiki/Q…, <lang>.wikipedia.org/wiki/…,
            musicbrainz.org/artist/…)

Filled in: name, aliases (other spellings, in Latin-script languages),
birth and death date, gender, country (ISO code), portrait (Wikimedia
Commons, else Open Opus), details (Wikipedia introduction), URLs
(Wikipedia, Wikidata, MusicBrainz, IMSLP, Discogs, website) and tags: the
musical occupations (Composer, Conductor, Pianist …) or the kind of
ensemble (Orchestra, Choir …), and the composer's epoch (Baroque,
Romantic …).

LANGUAGES below sets the preferred languages for the name and the
Wikipedia text.
"""

import json
import re
import sys
import urllib.parse
import urllib.request

LANGUAGES = ["de", "en"]  # name and Wikipedia text: the first that has one
ALIAS_LANGUAGES = ["de", "en", "fr", "it", "es", "nl", "pl", "cs", "sv", "da", "pt", "hu", "fi", "no"]
USER_AGENT = "StashClassicalMusicScraper/1.0 (https://github.com/rokdd/stash-classicmusic-plugins)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
MAX_RESULTS = 12

# What counts as music: words in an occupation's (English) label …
MUSIC_WORDS = re.compile(
    r"compos|conduct|pian|violin|viol|cell|singer|musician|organist|guitar|soprano|alto|tenor|bariton|bass|"
    r"mezzo|countertenor|harpsichord|flaut|flute|obo|clarinet|bassoon|trumpet|horn|trombon|tuba|percussion|"
    r"harp|lute|music|choir|chorus|opera|song|lied|cantor|kapellmeister|accompanist", re.I)
# … and in the kind of thing an ensemble is.
ENSEMBLE_WORDS = re.compile(r"orchestra|ensemble|choir|chorus|quartet|quintet|trio|band|musical group|opera company", re.I)

# Occupations that are about music but not performing or composing — left
# out of the tags.
NOT_A_ROLE = re.compile(r"educator|teacher|pedagog|musicolog|critic|theorist|arranger|producer|historian|"
                        r"collector|editor|publisher|writer|scholar|manager|engineer|instrument maker", re.I)


def role_tags(occupations):
    """Tags from occupation labels: performing and composing roles only,
    "woman conductor" → "Conductor", and "Musician" only if nothing more
    specific is there."""
    tags = []
    for o in occupations:
        if NOT_A_ROLE.search(o):
            continue
        o = re.sub(r"^(woman|female|male)\s+", "", o, flags=re.I)
        tag = o[:1].upper() + o[1:]
        if tag not in tags:
            tags.append(tag)
    specific = [t for t in tags if t.lower() != "musician"]
    return specific or tags


GENDERS = {"Q6581097": "MALE", "Q6581072": "FEMALE", "Q1052281": "TRANSGENDER_FEMALE",
           "Q2449503": "TRANSGENDER_MALE", "Q48270": "NON_BINARY"}


# -- requests ---------------------------------------------------------------------

def get_json(url, params=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def entities(ids, props="claims|labels|descriptions|aliases|sitelinks", languages=None):
    """Wikidata entities by id, 50 at a time."""
    out = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for n in range(0, len(ids), 50):
        params = {"action": "wbgetentities", "ids": "|".join(ids[n:n + 50]), "props": props, "format": "json"}
        if languages:
            params["languages"] = "|".join(languages)
        out.update(get_json(WIKIDATA_API, params).get("entities") or {})
    return out


def label(entity, languages=None):
    labels = entity.get("labels") or {}
    for lang in (languages or LANGUAGES) + ["en", "mul"]:
        if lang in labels:
            return labels[lang]["value"]
    return next((v["value"] for v in labels.values()), "")


def description(entity):
    descriptions = entity.get("descriptions") or {}
    for lang in LANGUAGES + ["en"]:
        if lang in descriptions:
            return descriptions[lang]["value"]
    return ""


def claim_values(entity, prop):
    values = []
    for claim in (entity.get("claims") or {}).get(prop, []):
        if claim.get("rank") == "deprecated":
            continue
        value = ((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if value is not None:
            values.append(value)
    return values


def ids_of(entity, prop):
    return [v["id"] for v in claim_values(entity, prop) if isinstance(v, dict) and "id" in v]


# -- what kind of performer ----------------------------------------------------------

def music_labels(entity, names):
    """(occupation labels that are music, ensemble kind labels)."""
    occupations = [names.get(q, "") for q in ids_of(entity, "P106")]
    kinds = [names.get(q, "") for q in ids_of(entity, "P31")]
    return [o for o in occupations if o and MUSIC_WORDS.search(o)], [k for k in kinds if k and ENSEMBLE_WORDS.search(k)]


def english_names(qids):
    found = entities(qids, props="labels", languages=["en"])
    return {q: (e.get("labels") or {}).get("en", {}).get("value", "") for q, e in found.items()}


def is_human(entity):
    return "Q5" in ids_of(entity, "P31")


# -- search ----------------------------------------------------------------------------

def search(name):
    ids = []
    for lang in LANGUAGES:
        data = get_json(WIKIDATA_API, {"action": "wbsearchentities", "search": name, "language": lang,
                                       "uselang": lang, "type": "item", "limit": 20, "format": "json"})
        ids += [hit["id"] for hit in data.get("search") or []]
    # Wikidata's quick search only matches the start of names; a surname
    # alone ("Mutter") needs its full-text search — people and ensembles.
    for extra in (f"{name} haswbstatement:P31=Q5", name):
        data = get_json(WIKIDATA_API, {"action": "query", "list": "search", "srsearch": extra,
                                       "srlimit": 20, "format": "json"})
        ids += [hit["title"] for hit in (data.get("query") or {}).get("search") or [] if hit["title"].startswith("Q")]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    found = entities(ids, props="claims|labels|descriptions")
    names = english_names([q for e in found.values() for q in ids_of(e, "P106") + ids_of(e, "P31")])
    music, others = [], []
    for qid in ids:
        e = found.get(qid)
        if not e or "missing" in e:
            continue
        occupations, kinds = music_labels(e, names)
        result = {"name": label(e), "disambiguation": description(e),
                  "urls": [f"https://www.wikidata.org/wiki/{qid}"]}
        if (is_human(e) and occupations) or kinds:
            music.append(result)
        elif is_human(e):
            others.append(result)
    # Musicians first; other people only if no musician matched.
    return (music or others)[:MAX_RESULTS]


# -- finding the Wikidata item --------------------------------------------------------

def qid_from_url(url):
    m = re.search(r"wikidata\.org/(?:wiki|entity)/(Q\d+)", url or "")
    if m:
        return m.group(1)
    m = re.search(r"//([a-z\-]+)\.(?:m\.)?wikipedia\.org/wiki/([^?#]+)", url or "")
    if m:
        site, title = f"{m.group(1).replace('-', '_')}wiki", urllib.parse.unquote(m.group(2)).replace("_", " ")
        data = get_json(WIKIDATA_API, {"action": "wbgetentities", "sites": site, "titles": title,
                                       "props": "info", "format": "json", "redirects": "yes"})
        return next((q for q in (data.get("entities") or {}) if q.startswith("Q")), None)
    m = re.search(r"musicbrainz\.org/artist/([0-9a-f-]{36})", url or "")
    if m:
        data = get_json(WIKIDATA_API, {"action": "query", "list": "search", "format": "json",
                                       "srsearch": f"haswbstatement:P434={m.group(1)}"})
        hits = (data.get("query") or {}).get("search") or []
        return hits[0]["title"] if hits else None
    return None


# -- the performer ------------------------------------------------------------------------

def wiki_date(value):
    """Wikidata time → "YYYY-MM-DD", or "YYYY-MM" / "YYYY" as precise as known."""
    m = re.match(r"[+]?(\d{1,4})-(\d{2})-(\d{2})", value.get("time", ""))
    if not m:
        return None
    year, month, day = m.groups()
    precision = value.get("precision", 11)
    year = year.zfill(4)
    return f"{year}-{month}-{day}" if precision >= 11 else f"{year}-{month}" if precision == 10 else year


def wikipedia_intro(entity):
    sitelinks = entity.get("sitelinks") or {}
    for lang in LANGUAGES:
        link = sitelinks.get(f"{lang}wiki")
        if not link:
            continue
        title = urllib.parse.quote(link["title"].replace(" ", "_"), safe="")
        try:
            summary = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title}")
        except Exception:  # noqa: BLE001
            continue
        if summary.get("extract"):
            return summary["extract"].strip(), f"https://{lang}.wikipedia.org/wiki/{title}"
    return "", None


def open_opus(name, birth_year):
    """The composer at Open Opus — matched by surname and year of birth."""
    surname = name.split()[-1] if name else ""
    if not surname:
        return None
    try:
        data = get_json(f"https://api.openopus.org/composer/list/search/{urllib.parse.quote(surname)}.json")
    except Exception:  # noqa: BLE001
        return None
    for c in data.get("composers") or []:
        if birth_year and (c.get("birth") or "")[:4] == birth_year:
            return c
    return None


def performer(qid):
    e = entities([qid]).get(qid)
    if not e or "missing" in e:
        raise SystemExit(f"Wikidata has no item {qid}.")
    linked = ids_of(e, "P106") + ids_of(e, "P31") + ids_of(e, "P27")
    linked_items = entities(linked, props="labels|claims", languages=["en"]) if linked else {}
    names = {q: (x.get("labels") or {}).get("en", {}).get("value", "") for q, x in linked_items.items()}
    occupations, kinds = music_labels(e, names)
    name = label(e)

    aliases = []
    for lang in ALIAS_LANGUAGES:
        for value in [((e.get("labels") or {}).get(lang) or {}).get("value")] + \
                [a["value"] for a in (e.get("aliases") or {}).get(lang, [])]:
            if value and "," not in value and value.lower() != name.lower() \
                    and value.lower() not in (a.lower() for a in aliases):
                aliases.append(value)

    births = [wiki_date(v) for v in claim_values(e, "P569")]
    deaths = [wiki_date(v) for v in claim_values(e, "P570")]
    birthdate = next((d for d in births if d), None)
    death_date = next((d for d in deaths if d), None)

    gender = next((GENDERS[q] for q in ids_of(e, "P21") if q in GENDERS), None)
    # Country: for a person, the country their place of birth lies in today
    # (Bonn → DE, Semyonovo → RU) — citizenships change and their order on
    # Wikidata says little; for an ensemble its own country. Else the first
    # citizenship, or — for a state that no longer exists (Electorate of
    # Cologne) — the present-day country it lies in.
    country = None
    places = ids_of(e, "P19") or []
    lands = [q for p in places for q in ids_of(entities([p], props="claims").get(p, {}), "P17")] + ids_of(e, "P17")
    for land in lands:
        codes = claim_values(entities([land], props="claims").get(land, {}), "P297")
        if codes:
            country = codes[0]
            break
    for q in ([] if country else ids_of(e, "P27")):
        item = linked_items.get(q, {})
        codes = claim_values(item, "P297")
        if not codes:
            for successor in ids_of(item, "P17") + ids_of(item, "P1366"):
                codes = claim_values(entities([successor], props="claims").get(successor, {}), "P297")
                if codes:
                    break
        if codes:
            country = codes[0]
            break

    images = [
        "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(f.replace(" ", "_")) + "?width=1000"
        for f in claim_values(e, "P18")
    ]
    details, wikipedia_url = wikipedia_intro(e)

    urls = []
    if wikipedia_url:
        urls.append(wikipedia_url)
    sitelinks = e.get("sitelinks") or {}
    for lang in LANGUAGES:
        link = sitelinks.get(f"{lang}wiki")
        if link:
            urls.append(f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(link["title"].replace(" ", "_")))
    urls.append(f"https://www.wikidata.org/wiki/{qid}")
    urls += [f"https://musicbrainz.org/artist/{v}" for v in claim_values(e, "P434")]
    urls += ["https://imslp.org/wiki/Category:" + urllib.parse.quote(re.sub(r"^Category:", "", v).replace(" ", "_"), safe=",:_()'")
             for v in claim_values(e, "P839")]
    urls += [f"https://www.discogs.com/artist/{v}" for v in claim_values(e, "P1953")]
    urls += [v for v in claim_values(e, "P856") if isinstance(v, str)]

    tags = role_tags(occupations) + [k[:1].upper() + k[1:] for k in kinds]
    if any(re.search(r"compos", o, re.I) for o in occupations):
        opus = open_opus(name, (birthdate or "")[:4])
        if opus:
            if opus.get("epoch"):
                tags.append(opus["epoch"])
            if not images and opus.get("portrait"):
                images.append(opus["portrait"])

    result = {
        "name": name,
        "aliases": ", ".join(aliases),
        "urls": list(dict.fromkeys(urls)),
        "tags": [{"name": t} for t in dict.fromkeys(tags)],
        "details": details,
    }
    if birthdate:
        result["birthdate"] = birthdate
    if death_date:
        result["death_date"] = death_date
    if gender:
        result["gender"] = gender
    if country:
        result["country"] = country
    if images:
        result["images"] = images
        result["image"] = images[0]
    return result


# -- Stash ----------------------------------------------------------------------------------

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "search"
    raw = sys.stdin.read()
    data = json.loads(raw) if raw.strip() else {}
    if mode == "search":
        print(json.dumps(search((data.get("name") or "").strip())))
        return
    if mode == "url":
        qid = qid_from_url(data.get("url"))
        if not qid:
            raise SystemExit(f"No Wikidata item for {data.get('url')}.")
        print(json.dumps(performer(qid)))
        return
    # fragment: a search result or the performer as it is — by a URL it
    # has, else by its name (the first musician found).
    urls = list(data.get("urls") or []) + ([data["url"]] if data.get("url") else [])
    qid = next((q for q in (qid_from_url(u) for u in urls) if q), None)
    if not qid and data.get("name"):
        hits = search(data["name"])
        qid = qid_from_url(hits[0]["urls"][0]) if hits else None
    if not qid:
        raise SystemExit("Nothing found on Wikidata.")
    print(json.dumps(performer(qid)))


if __name__ == "__main__":
    # Stash reads the result from stdout: always give it JSON — "null" (no
    # result) when there's none — and the reason in its log (stderr).
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            sys.stderr.write(f"Classical Music: {exc.code}\n")
            print("[]" if (sys.argv[1:2] or ["search"])[0] == "search" else "null")
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Classical Music: {type(exc).__name__}: {exc}\n")
        print("[]" if (sys.argv[1:2] or ["search"])[0] == "search" else "null")
