"""A concert's programme, read from pasted (rich) text or a web page —
everything there is: title, date, venue, station, description, links, the
performers (conductor, soloists, orchestra, choir), the composers, and the
programme itself (composer → work → movements) as chapters.

  parse(text, meta=None) → {"title", "date", "venue", "studio", "details",
      "urls", "performers", "composers", "chapters": [{"composer", "work",
      "movement", "title"}]}
  page(url) → (text, meta): the page's main text, and what it says about
      itself (title, description, an Event's date, venue and performers —
      schema.org JSON-LD)

Used by Markers as Chapters ("Paste a programme (rich text) or a page…",
mode programme_parse). The reading of performers, composers and dates is
the one of the Classical Concerts scraper (copied: the plugin doesn't need
that scraper installed). Standard library only.
"""

import html
import json
import re
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (StashMarkersAsChapters; https://github.com/rokdd/stash-classicmusic-plugins)"


# -- from the Classical Concerts scraper -------------------------------------------------------

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
    # lines, parts after "; " and sentences ("… Norrington. Mitwirkende sind …")
    for raw in re.split(r"\n|\s\|\s|;\s|(?<=[a-zäöüß])\.\s+(?=[A-ZÄÖÜ])", text or ""):
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
        # "Name, Dirigent" / "Name, Klavier" — also after a lead-in
        # ("Mitwirkende in diesem Jahr sind Bryn Terfel, Bassbariton")
        m = re.match(r"^(.+?),\s*(.+)$", line)
        if m and ROLE_RE.match(m.group(2)):
            words = m.group(1).split()
            name = next((" ".join(words[-n:]) for n in (4, 3, 2) if len(words) >= n and name_like(" ".join(words[-n:]))
                         and (len(words) == n or words[-n - 1][:1].islower())), None)
            if name:
                performers.append(name)
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
    # in running text: "unter der Leitung von Sir Roger Norrington",
    # "Es spielt das BBC Symphony Orchestra", "mit dem hr-Sinfonieorchester"
    flat = re.sub(r"\s+", " ", text or "")
    for m in LED_BY.finditer(flat):
        performers.append(m.group(1))
    for m in ENSEMBLE_IN_TEXT.finditer(flat):
        if len(m.group(1).split()) >= 2:  # "the Orchestra" alone is no name
            performers.append(m.group(1))
    return performers, composers


NAME_WORD = r"(?:[A-Z]\.|[A-ZÄÖÜÉ][\w'’-]+|van|von|de|der|den|di|da|du|le|la|del|zu)"  # no full stop: a sentence ends
LED_BY = re.compile(rf"(?:unter (?:der )?(?:musikalischen )?Leitung von|dirigiert von|Dirigent(?:in)? ist|conducted by|"
                    rf"under the baton of)\s+((?:Sir |Dame )?[A-ZÄÖÜÉ][\w'’-]+(?:\s+{NAME_WORD}){{1,3}})")
ENSEMBLE_IN_TEXT = re.compile(r"(?:spielt das|spielen die|spielt die|mit dem|mit der|mit den|with the|by the|"
                              r"das|der|die|the)\s+((?:[A-ZÄÖÜ][\w-]*\s+){0,4}(?:Symphony Orchestra|Philharmonic Orchestra|"
                              r"Chamber Orchestra|Orchestra|Orchester|Sinfonieorchester|Symphonieorchester|Philharmoniker|"
                              r"Philharmonic|Symphony Chorus|Chorus|Choir|Chor|Singers|Ensemble)\b)")



def unique(names):
    import unicodedata
    out, seen = [], set()
    for n in names:
        n = unicodedata.normalize("NFC", re.sub(r"\s+", " ", (n or "").strip(" .,;")))
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out



PRESS = re.compile(r"/presse|presseportal|pressemitteilung|pressemeldung|/press/|/medien/medienmitteilung", re.I)
CHANNELS = re.compile(r"(?:Das Erste|NDR|WDR|BR|SWR|MDR|hr|rbb|SR|Radio Bremen|ZDF|3sat|ARTE|arte|ORF\s?\w*|SRF\s?\w*|"
                      r"ONE|ZDFneo|ZDFinfo|tagesschau24|ARD[- ]alpha|Phoenix|KiKA|Deutschlandfunk\w*|NDR Kultur|WDR 3|"
                      r"BR-KLASSIK|SWR2|MDR KLASSIK|hr2|rbbKultur)(?:\s+Fernsehen|\s+Kultur|\s+Klassik)?\b")




# -- web pages -------------------------------------------------------------------------------------

def unwrap(url):
    """A link copied from Google's results → the page itself."""
    if re.search(r"//(www\.)?google\.[a-z.]+/url\?", url or ""):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        target = q.get("url") or q.get("q")
        if target:
            return target[0]
    return url


def html_to_text(page):
    """HTML → text with its structure: paragraphs, list items, headings and
    table rows on lines of their own; scripts, styles, navigation, header
    and footer left out; the links kept as "text <url>" for the links list."""
    page = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|form|aside)\b.*?</\1>", " ", page or "")
    page = re.sub(r"(?is)<!--.*?-->", " ", page)
    page = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>|</div>|</dd>|</dt>|</section>|</article>", "\n", page)
    page = re.sub(r"(?i)</t[dh]>", " \t ", page)
    page = re.sub(r"<[^>]+>", "", page)
    text = html.unescape(page).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def links_in(page):
    return list(dict.fromkeys(u for u in re.findall(r'href="(https?://[^"#]+)"', page or "")))


def page(url):
    """(main text, meta) of a web page."""
    url = unwrap(url.strip())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.8"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8", "replace")

    def meta(prop):
        m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]+content="([^"]*)"', raw)
        return html.unescape(m.group(1)) if m else ""
    info = {"url": url, "title": meta("og:title") or (re.search(r"(?is)<title>(.*?)</title>", raw) or [None, ""])[1].strip(),
            "description": meta("og:description") or meta("description"), "site": meta("og:site_name")}
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if not isinstance(item, dict):
                continue
            kind = item.get("@type")
            kind = kind if isinstance(kind, list) else [kind]
            if any(k and ("Event" in k) for k in kind):
                info["title"] = item.get("name") or info["title"]
                info["date"] = (item.get("startDate") or "")[:10] or None
                place = item.get("location")
                place = place[0] if isinstance(place, list) and place else place
                if isinstance(place, dict):
                    info["venue"] = place.get("name")
                people = item.get("performer") or []
                people = people if isinstance(people, list) else [people]
                info["performers"] = [p.get("name") if isinstance(p, dict) else str(p) for p in people if p]
                if item.get("description"):
                    info["description"] = html.unescape(str(item["description"]))
    # the page's own part: its <main> or <article>, else the whole body
    main = re.search(r"(?is)<main\b.*?</main>", raw) or re.search(r"(?is)<article\b.*?</article>", raw)
    text = html_to_text(main.group(0) if main else raw)
    info["links"] = links_in(main.group(0) if main else raw)
    return text, info


# -- the programme ----------------------------------------------------------------------------------

WORK_WORDS = re.compile(
    r"\b(sinfonie|symphonie|symphony|konzert|concerto|ouvertüre|ouverture|overture|suite|sonate|sonata|serenade|"
    r"variationen|variations|quartett|quartet|quintett|trio|messe|mass|requiem|oratorium|kantate|cantata|"
    r"arie|aria|walzer|waltz|polka|marsch|march|galopp|lied|lieder|rhapsodie|rhapsody|tondichtung|poème|"
    r"präludium|prelude|fuge|fugue|nocturne|etüde|étude|ballade|scherzo|fantasie|fantasia|op\.|opus|nr\.|no\.|"
    r"bwv|kv|k\.\s*\d|hob\.|woo|d\s*\d+|wab|rv\s*\d)\b|[„\"“«]", re.I)
MOVEMENT = re.compile(r"^(?:[IVX]{1,4}\.?|\d{1,2}\.)\s+\S|^(?:allegro|adagio|andante|presto|largo|lento|vivace|moderato|"
                      r"scherzo|finale|rondo|menuett|minuet|allegretto|larghetto|andantino|grave|maestoso|sostenuto|"
                      r"tempo di|alla )\b", re.I)
YEARS = re.compile(r"\s*[\(\[]\s*\*?\s*\d{4}\s*(?:[–-]\s*\d{4})?\s*[\)\]]\s*$")


def composer_line(line):
    """"Ludwig van Beethoven (1770–1827)", "Johannes Brahms:" → the name."""
    name = YEARS.sub("", line).strip().rstrip(":").strip()
    return name if name_like(name) and not ROLE_RE.match(name) and not ensemble_like(name) else None


def programme(text):
    """[(composer, work, movement)] in the text's order."""
    out = []
    composer, work = None, None
    for raw in re.split(r"\n|;\s+(?=[A-ZÄÖÜ])", text or ""):
        line = raw.strip(" •·*\t")
        if not line or len(line) > 160:
            continue
        # "Composer: Work" / "Composer – Work" on one line
        m = re.match(r"^([^:–]{3,60}?)\s*(?::|\s[–-]\s)\s*(.+)$", line)
        if m and composer_line(m.group(1)) and WORK_WORDS.search(m.group(2)):
            composer, work = composer_line(m.group(1)), m.group(2).strip(" .")
            out.append((composer, work, None))
            continue
        name = composer_line(line)
        if name and not WORK_WORDS.search(line):
            composer, work = name, None
            continue
        if composer and MOVEMENT.match(line) and work:
            # a movement of the work before: it replaces the work's own entry
            if out and out[-1] == (composer, work, None):
                out.pop()
            out.append((composer, work, line.strip(" .")))
            continue
        if composer and WORK_WORDS.search(line):
            work = line.strip(" .")
            out.append((composer, work, None))
    return out


def parse(text, meta=None):
    meta = meta or {}
    text = (text or "").strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    performers, composers = from_text(text)
    performers = unique(list(meta.get("performers") or []) + performers)
    chapters = []
    for composer, work, movement in programme(text):
        composers.append(composer)
        title = f"{composer} – {work}" + (f" – {movement}" if movement else "")
        chapters.append({"composer": composer, "work": work, "movement": movement, "title": title})
    composers = unique(composers)
    performers = [p for p in performers if p.lower() not in {c.lower() for c in composers}]
    # the broadcast date ("Sendetermin: …") before any date in the text
    date = meta.get("date")
    when = re.search(r"(?:Sende(?:termin|zeit|datum)|Ausstrahlung|Konzert(?:datum|termin)|Datum|Termin|Date)\b[^\n]*", text, re.I)
    if not date and when:
        date = concert_date(when.group(0))
    date = date or concert_date(text)
    if not date:
        m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.((?:19|20)\d\d)\b", text)
        if m:
            date = f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    venue = meta.get("venue")
    if not venue:
        venue = next((l for l in lines if len(l) <= 80 and re.search(
            r"\b(saal|halle|hall|konzerthaus|philharmonie|elbphilharmonie|oper|opera|theater|theatre|kirche|dom|"
            r"cathedral|festspielhaus|arena|musikverein|tonhalle|gewandhaus|kkl|royal albert)\b", l, re.I)), None)
    studio = None
    channel = CHANNELS.findall(when.group(0)) if when else []
    if channel:
        studio = channel[-1]
    title = (meta.get("title") or "").strip() or (lines[0] if lines and len(lines[0]) <= 140 else "")
    title = re.sub(r"\s*[|–-]\s*[\w. ]+\.(?:de|at|ch|com|org)$", "", title).strip()
    details = (meta.get("description") or "").strip()
    if len(text) > len(details):
        details = text[:5000].strip()
    urls = [u for u in [meta.get("url")] if u] + [u for u in re.findall(r"https?://[^\s<>\"]+", text)] + list(meta.get("links") or [])[:0]
    return {"title": title, "date": date, "venue": venue, "studio": studio, "details": details,
            "urls": list(dict.fromkeys(urls)), "performers": performers, "composers": composers, "chapters": chapters}
