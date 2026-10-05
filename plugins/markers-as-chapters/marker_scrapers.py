"""
Marker scrapers — the Python side of the Markers as Chapters plugin
(everything it needs is in this plugin).

Stash's scrapers have no "marker" type, and a plugin can't add one to
Stash itself. So this is a marker scraper system that works like Stash's
own: scrapers are .yaml (or .yml) files, in Stash's format, with three new
kinds of entry —

    name: Video file chapters
    markerByFragment:            # from the scene itself
      action: script
      script:
        - python
        - video_chapters.py
    markerByURL:                 # from a URL (one of the scene's, or typed)
      - action: script
        url:
          - youtube.com
          - youtu.be
        script:
          - python
          - online_chapters.py
    markerByText:                # from text you paste or a file you pick
      action: script
      script:
        - python
        - plain_text.py

A script gets JSON on stdin — {"scene": {...}} for a fragment, plus
"url" for a URL, plus "text" for text — and prints a JSON list of markers:

    [{"seconds": 0, "end_seconds": 512.4, "title": "I. Allegro con brio",
      "primary_tag": "Movement", "tags": ["Beethoven"]}, ...]

(only "seconds" is required) — or {"markers": [...], "notes": "..."}, the
notes shown above the markers in the review dialog. An action may set "timeout: <seconds>"
(default 180), and a scraper "description:" — shown in the text dialog — and
"fragmentInMenu: true" to be listed at the top of the menu even though it
handles URLs (it reads the scene's own files too).
Scripts run in their scraper's folder, with the environment variables
STASH_FFMPEG, STASH_FFPROBE (Stash's own ffmpeg / ffprobe) and
STASH_YTDLP (the "Path to yt-dlp" setting; else Scene Improvements' one;
else yt-dlp on the PATH) pointing at the tools to use.

The ones inside Stash's plugins folder must be .yaml: Stash reads every
.yml there as a plugin of its own.

Scrapers are read from the "marker-scrapers" folder next to this file
(the ones that come with the plugin) and from the folder in the "Marker
scrapers folder" setting. Runs through Stash's runPluginOperation:
  - marker_scrapers_list: every scraper with what it can do
  - marker_scrape:        args "scraper" (its id), "scene_id", optional
                          "url" or "text" — the markers it found
  - marker_pauses:        args "scene_id" — the pauses in the scene's
                          audio, for the review dialog's check
  - marker_composers:     composers named in existing markers' titles —
                          proposals, or with "apply" applied (see below)
Standard library only.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

PLUGIN_ID = "markersAsChapters"
# These settings used to be Marker Improvements' — still read from there
# when they aren't set here.
OLD_PLUGIN_ID = "markerImprovements"
SETTING_KEYS = ("scrapedMarkerTag", "markerScrapersPath", "ytdlpPath")

BUILT_IN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marker-scrapers")
sys.path.insert(0, BUILT_IN_DIR)
from encoding_fix import fix_text  # noqa: E402 — lives with the scrapers
SCRIPT_TIMEOUT = 180


# ---------------------------------------------------------------------------
# A small YAML reader — enough for scraper files: nested mappings, lists
# (of scalars or of mappings), comments and quoted strings. The standard
# library has no YAML parser.
# ---------------------------------------------------------------------------

def _scalar(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _strip_comment(line):
    out, quote = [], None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).rstrip()


def parse_yaml(text):
    lines = []
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip(" ")), line.strip()))

    def block(i, indent):
        """Parses the block starting at lines[i] (indented `indent`)."""
        if i < len(lines) and lines[i][1].startswith("- "):
            items = []
            while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                rest = lines[i][1][2:].strip()
                if re.match(r"^[^:\s][^:]*:(\s|$)", rest):
                    # A mapping as list item: its first key is on the dash line.
                    sub = [(indent + 2, rest)]
                    j = i + 1
                    while j < len(lines) and lines[j][0] > indent:
                        sub.append(lines[j])
                        j += 1
                    saved = lines[:]
                    lines[i:j] = sub
                    value, _ = block(i, indent + 2)
                    lines[:] = saved
                    items.append(value)
                    i = j
                else:
                    items.append(_scalar(rest))
                    i += 1
            return items, i
        mapping = {}
        while i < len(lines) and lines[i][0] == indent:
            key, _, value = lines[i][1].partition(":")
            key, value = key.strip(), value.strip()
            i += 1
            if value:
                mapping[key] = _scalar(value)
            elif i < len(lines) and lines[i][0] > indent:
                mapping[key], i = block(i, lines[i][0])
            elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                mapping[key], i = block(i, indent)  # list at the key's own indent
            else:
                mapping[key] = None
        return mapping, i

    value, _ = block(0, lines[0][0]) if lines else ({}, 0)
    return value


# ---------------------------------------------------------------------------
# Finding scrapers
# ---------------------------------------------------------------------------

def scraper_dirs(settings):
    dirs = [BUILT_IN_DIR]
    extra = (settings.get("markerScrapersPath") or "").strip()
    if extra:
        dirs.append(os.path.expanduser(extra))
    return [d for d in dirs if os.path.isdir(d)]


def load_scrapers(settings):
    scrapers = {}
    for folder in scraper_dirs(settings):
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if not name.lower().endswith((".yml", ".yaml")):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, encoding="utf-8") as f:
                        config = parse_yaml(f.read())
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(config, dict) or not (config.get("markerByFragment") or config.get("markerByURL") or config.get("markerByText")):
                    continue  # not a marker scraper (e.g. one of Stash's own)
                scraper_id = os.path.splitext(name)[0]
                by_url = config.get("markerByURL") or []
                if isinstance(by_url, dict):
                    by_url = [by_url]
                scrapers[scraper_id] = {
                    "id": scraper_id,
                    "name": config.get("name") or scraper_id,
                    "description": config.get("description") or "",
                    "dir": root,
                    "fragment": config.get("markerByFragment"),
                    "by_url": by_url,
                    "by_text": config.get("markerByText"),
                    "fragment_in_menu": bool(config.get("fragmentInMenu")),
                    "text_label": config.get("textLabel") or "",
                }
    return scrapers


def url_patterns(scraper):
    patterns = []
    for entry in scraper["by_url"]:
        urls = entry.get("url") or []
        patterns.extend([urls] if isinstance(urls, str) else urls)
    return patterns


def list_scrapers(settings):
    return [
        {"id": s["id"], "name": s["name"], "fragment": bool(s["fragment"]), "urls": url_patterns(s),
         "text": bool(s["by_text"]), "description": s["description"],
         "fragment_in_menu": s.get("fragment_in_menu", False), "text_label": s.get("text_label", "")}
        for s in sorted(load_scrapers(settings).values(), key=lambda s: s["name"].lower())
    ]


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------

def scene_for_scraper(gql, scene_id):
    data = gql(
        "query($id: ID!) { findScene(id: $id) { id title code details date urls "
        "files { path duration } scene_markers { id seconds end_seconds title primary_tag { id name } tags { id name } } } }",
        {"id": scene_id},
    )
    return data["findScene"]


def run_action(scraper, action, payload, env_extra):
    if not isinstance(action, dict) or action.get("action") != "script":
        raise ValueError(f"Scraper {scraper['name']}: only 'action: script' is supported for markers.")
    cmd = action.get("script") or []
    if isinstance(cmd, str):
        cmd = [cmd]
    if not cmd:
        raise ValueError(f"Scraper {scraper['name']}: no script given.")
    if cmd[0] in ("python", "python3"):
        cmd = [sys.executable] + cmd[1:]
    env = {**os.environ, **env_extra}
    proc = subprocess.run(
        cmd, input=json.dumps(payload), capture_output=True, text=True,
        cwd=scraper["dir"], env=env, timeout=int(action.get("timeout") or SCRIPT_TIMEOUT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Scraper {scraper['name']} failed: {(proc.stderr or proc.stdout)[-800:]}")
    try:
        result = json.loads(proc.stdout or "[]")
    except ValueError as exc:
        raise RuntimeError(f"Scraper {scraper['name']} didn't print JSON: {exc}") from exc
    if isinstance(result, list):
        return result, "", None
    # still working in the background (Text in the picture): said by "running"
    run_action.running = bool(result.get("running"))
    run_action.start_job = bool(result.get("start_job"))
    return result.get("markers", []), str(result.get("notes") or ""), result.get("pieces")


def normalise(markers):
    out = []
    for m in markers:
        if not isinstance(m, dict) or m.get("seconds") is None:
            continue
        tags = m.get("tags") or []
        out.append({
            "seconds": round(float(m["seconds"]), 3),
            "end_seconds": round(float(m["end_seconds"]), 3) if m.get("end_seconds") is not None else None,
            "title": tidy(fix_text(str(m.get("title") or ""))),
            "primary_tag": fix_text(str(m.get("primary_tag") or "")),
            "tags": [fix_text(str(t)) for t in (tags if isinstance(tags, list) else [tags]) if t],
        })
    out.sort(key=lambda m: m["seconds"])
    return out


def scrape(gql, args, settings, env_extra):
    scrapers = load_scrapers(settings)
    scraper = scrapers.get(args.get("scraper"))
    if not scraper:
        raise ValueError(f"No marker scraper '{args.get('scraper')}'.")
    scene = scene_for_scraper(gql, args.get("scene_id"))
    if not scene:
        raise ValueError(f"No scene {args.get('scene_id')}.")
    url = (args.get("url") or "").strip()
    text = args.get("text") or ""
    payload = {"scene": scene}
    if text.strip():
        action = scraper["by_text"]
        if not action:
            raise ValueError(f"Scraper {scraper['name']} doesn't read text.")
        payload["text"] = text
    elif url:
        action = next(
            (e for e in scraper["by_url"]
             if any(p and p in url for p in ([e.get("url")] if isinstance(e.get("url"), str) else e.get("url") or []))),
            None,
        )
        if not action:
            raise ValueError(f"Scraper {scraper['name']} doesn't handle {url}.")
        payload["url"] = url
    else:
        action = scraper["fragment"]
        if not action:
            raise ValueError(f"Scraper {scraper['name']} only scrapes URLs.")
    run_action.running = run_action.start_job = False
    markers, notes, pieces = run_action(scraper, action, payload, env_extra)
    if run_action.running:
        job = None
        if run_action.start_job:
            # a Stash task does the long work: the job queue doesn't end it
            # when the browser's request ends
            name = os.path.basename(((scene.get("files") or [{}])[0]).get("path") or "") or scene.get("title") or ""
            job = gql("""mutation($id: ID!, $d: String, $a: Map) { runPluginTask(plugin_id: $id, description: $d, args_map: $a) }""",
                      {"id": PLUGIN_ID, "d": f"Text in the picture: {name}",
                       "a": {"mode": "marker_ocr_job", "scene_id": str(scene.get("id"))}})["runPluginTask"]
        return {"scraper": scraper["name"], "markers": [], "notes": notes, "running": True, "job": job,
                "existing": scene.get("scene_markers") or []}
    markers = normalise(markers)
    if len(markers) > 1 and len({m["seconds"] for m in markers}) == 1:
        # Every marker at the same time: the source had no real times.
        titles = "; ".join(dict.fromkeys(m["title"] for m in markers if m["title"]))
        markers = []
        notes = (notes + " " if notes else "") + (
            "All markers found start at the same time, so the source has no real times. "
            + (f"Titles: {titles}. Paste them into Plain text to place them at the pauses in the audio." if titles else ""))
    try:
        matched = suggest_tags(gql, markers, settings)
    except Exception as exc:  # noqa: BLE001
        matched, notes = 0, (notes + " " if notes else "") + f"(Couldn't match tags by name: {exc})"
    if matched:
        notes = (notes + " " if notes else "") + \
            f"{matched} marker{'' if matched == 1 else 's'} got tags from their titles (e.g. composers)."
    if pieces:
        # Titles placed at the pauses: every title in order (also ones that
        # got no piece), with tags and stripped titles like the markers — the
        # dialog places them again when a part is marked as not music.
        pieces = normalise([{**p, "seconds": 0} for p in pieces])
        try:
            suggest_tags(gql, pieces, settings)
        except Exception:  # noqa: BLE001
            pass
        pieces = [{k: p[k] for k in ("title", "title_stripped", "tags", "primary_tag") if k in p} for p in pieces]
        for p in pieces:
            p.setdefault("title_stripped", p["title"])
    return {"scraper": scraper["name"], "markers": markers, "notes": notes, "pieces": pieces or None,
            "existing": scene.get("scene_markers") or []}


# ---------------------------------------------------------------------------
# Filling in tags from the titles (composers …)
# ---------------------------------------------------------------------------
#
# The tags under the "Fill in tags under" setting (default: Composers — the
# composer tags Tag Improvements keeps) are looked for in every marker's
# title, and in the tag names a scraper suggests:
#   - the tag's whole name or one of its aliases ("Ludwig van Beethoven",
#     "Beethoven"), as whole words — always used;
#   - or just a part: the last word of the name or of an alias, the surname
#     ("Beethoven: Symphony No. 5" → Ludwig van Beethoven) — used when only
#     one tag has that surname (two Bachs or Strausses: neither, unless the
#     title has more of the name). Spellings that differ only in the last
#     letters count too ("Rachmaninow" / "Rachmaninoff", "Mussorgski" /
#     "Mussorgsky"); for others give the tag an alias.
# Upper/lower case and accents are ignored. A scraper's suggested name that
# matches is replaced by the tag's name.

DEFAULT_SUGGEST_UNDER = "Composers, Soloists"


def _plain(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _similar(a, b):
    """Same surname, maybe in another spelling of its last letters."""
    if a == b:
        return True
    if min(len(a), len(b)) < 6 or abs(len(a) - len(b)) > 2:
        return False  # "Walzer" isn't a spelling of "Walzerkönig"
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    return common >= max(5, min(len(a), len(b)) - 2)


def tags_under(gql, names):
    """Tags (id, name, aliases) below the named parent tags, at any depth."""
    found = []
    for name in names:
        parent = gql(
            'query($n: String!) { findTags(tag_filter: { name: { value: $n, modifier: EQUALS } }, filter: { per_page: 1 }) { tags { id } } }',
            {"n": name},
        )["findTags"]["tags"]
        if not parent:
            continue
        found += gql(
            "query($ids: [ID!]) { findTags(tag_filter: { parents: { value: $ids, modifier: INCLUDES, depth: -1 } }, "
            "filter: { per_page: -1 }) { tags { id name aliases } } }",
            {"ids": [parent[0]["id"]]},
        )["findTags"]["tags"]
    return found


class TagMatcher:
    def __init__(self, tags):
        self.tags = []
        for t in tags:
            phrases = [p for p in {_plain(x) for x in [t["name"], *(t.get("aliases") or [])]} if p]
            # the surname: the last real name word ("Johann Strauss Sohn" → strauss)
            surnames = set()
            for p in phrases:
                words = [w for w in p.split() if w not in SUFFIXES and w not in PARTICLES]
                if words and len(words[-1]) >= 4:
                    surnames.add(words[-1])
            self.tags.append((t["name"], phrases, surnames))

    def match(self, text):
        """The tags named in text. First the part before the first separator
        (" - ", " – ", ": ", " | "), which in a title like "Johann Strauss
        Vater – Radetzky-Marsch" is the composer: if it is exactly a tag's
        name or alias, that tag it is — plus any named after it. Else the
        whole text, word by word (see _match)."""
        head = re.match(r"^\s*(.+?)\s*(?:\s[-–—]\s|:\s|\s\|\s)\s*(.*)$", text or "", re.S)
        if head:
            plain_head = _plain(head.group(1))
            exact = [name for name, phrases, _s in self.tags if plain_head in phrases]
            if exact:
                rest = [n for n in self._match(head.group(2)) if n not in exact]
                return list(dict.fromkeys(exact + rest))
        return self._match(text)

    def _match(self, text):
        words = _plain(text).split()
        # Whole names and aliases, with where in the title they are (word
        # positions).
        words_of = {name: {w for p in phrases for w in p.split()} for name, phrases, _s in self.tags}

        father = {"vater", "i", "sen", "senior", "elder", "sr", "pere", "padre", "starszy"}
        son = {"sohn", "ii", "jun", "junior", "younger", "jr", "fils", "hijo", "mladsi", "syn"}

        def wrong_generation(name, end):
            """A father/son word right after the name that doesn't fit the tag:
            "Johann Strauss Vater" and the son's tag (aliases Sohn, II, jr.)."""
            after = words[end] if end < len(words) else ""
            group, other = (father, son) if after in father else (son, father) if after in son else (None, None)
            return bool(group) and not (words_of[name] & group) and bool(words_of[name] & other)

        def other_first_name(name, i):
            """The word before position i is a name word of another tag, not
            of this one: "Johann Strauss" isn't Joseph Strauss's "Strauss"."""
            if i == 0:
                return False
            prev = words[i - 1]
            if prev in PARTICLES or prev in SUFFIXES or len(prev) < 3 or prev in words_of[name]:
                return False
            return any(prev in ws for other, ws in words_of.items() if other != name)

        spans = {}
        for name, phrases, _s in self.tags:
            for p in phrases:
                pw = p.split()
                for i in range(len(words) - len(pw) + 1):
                    if words[i:i + len(pw)] == pw and not (len(pw) == 1 and other_first_name(name, i)):
                        spans.setdefault(name, []).append((i, i + len(pw)))
        # A match that lies inside a longer one of another tag doesn't count:
        # Joseph Strauss's alias "Strauss" in "Johann Strauss Sohn" (an alias
        # of Johann Strauss).
        def inside(a, b):
            return b[0] <= a[0] and a[1] <= b[1] and (b[1] - b[0]) > (a[1] - a[0])
        # "Johann Strauss Vater" isn't the tag of the son (aliases Sohn, II,
        # jr. …), nor the other way round: a father/son word right after the
        # name has to fit the tag.
        for name in list(spans):
            fitting = [(a, b) for a, b in spans[name] if not wrong_generation(name, b)]
            if fitting:
                spans[name] = fitting
            else:
                del spans[name]
        full = [name for name, own in sorted(spans.items(), key=lambda kv: min(s[0] for s in kv[1]))
                if not all(any(inside(s, o) for other, theirs in spans.items() if other != name for o in theirs)
                           for s in own)]
        covered = {i for name in full for a, b in spans[name] for i in range(a, b)}
        # A surname alone counts when exactly one tag has it, and no tag
        # matched by its whole name explains it already.
        unique = []
        for i, w in enumerate(words):
            if i in covered:
                continue
            names = [name for name, _p, surnames in self.tags
                     if any(_similar(w, s) for s in surnames) and not other_first_name(name, i)
                     and not wrong_generation(name, i + 1)]
            if len(names) == 1 and names[0] not in full:
                unique.append(names[0])
        return list(dict.fromkeys(full + unique))


# -- the tags' names taken out of the titles ---------------------------------
#
# "Johann Strauss Sohn – Im Krapfenwaldl" with the tag Johann Strauss II →
# "Im Krapfenwaldl". A run of words that belong to the tag's name or
# aliases (spellings that differ only at the end count: Sergej / Sergei),
# with initials ("J.", "C.P.E."), particles (van, von, de …) and suffixes
# (Sohn, Vater, II, jr. …) — and at least one real name word in it — is
# taken out, then the separators left at the ends. A title that would be
# empty is kept as it was. The review dialog has a switch for it.

# -- tidy titles ----------------------------------------------------------------
#
# Every title — and every title with names taken out — is tidied: unusual
# spaces become normal ones, brackets left empty go, separators side by side
# become one, separators at the ends go, and no space stays before , ; or .

SEPARATORS = "-–—‒―−:;,/|·•~_»«"
_SPACES = re.compile("[\u00a0\u2007\u2009\u202f\u2002\u2003\t]")
_EMPTY_BRACKETS = re.compile(r"[(\[{]\s*[-–—:;,/|·•~_]*\s*[)\]}]")
_SEP_RUN = re.compile(r"\s*([%s])(?:\s*[%s])+\s*" % (re.escape(SEPARATORS), re.escape(SEPARATORS)))


def tidy(title):
    if not title:
        return title
    import unicodedata
    title = unicodedata.normalize("NFC", title)  # "u" + "¨" → "ü": one letter, one word
    out = _SPACES.sub(" ", title)
    # brackets left with just a linking word: "(für )", "(by)"
    out = re.sub(r"[(\[]\s*(?:für|fuer|for|by|von|de|di|du|of|nach|after|à)?\s*[)\]]", " ", out, flags=re.I)
    out = _EMPTY_BRACKETS.sub(" ", out)
    out = re.sub(r"([(\[])\s+", r"\1", out)
    out = re.sub(r"\s+([)\]])", r"\1", out)
    out = re.sub(r"\s+\.(?=\s|$)", " ", out)  # a full stop on its own
    out = _SEP_RUN.sub(lambda m: f" {m.group(1)} " if m.group(1) not in ",;:" else f"{m.group(1)} ", out)
    out = re.sub(r"\s+([,;.])", r"\1", out)
    out = re.sub(r"\s+", " ", out)
    out = out.strip(" " + SEPARATORS).strip()
    return out or title.strip()


PARTICLES = {"van", "von", "de", "der", "den", "di", "da", "du", "le", "la", "y", "del", "dos", "das", "zu"}
SUFFIXES = {"sohn", "vater", "ii", "iii", "iv", "jr", "sr", "jun", "sen", "junior", "senior", "the", "younger", "elder", "d", "j", "a", "ä"}
EDGE_SEPARATORS = " \t" + SEPARATORS
TRAILING_LINKS = re.compile(r"\s+(by|von|de|di|of|from|nach)\s*$", re.I)


def _tag_words(names):
    words = set()
    for n in names:
        words.update(w for w in _plain(n).split() if len(w) > 1)
    return words


def strip_names(title, tag_names):
    """title without the names in tag_names (lists of name + aliases)."""
    import unicodedata
    title = unicodedata.normalize("NFC", title or "")
    tokens = [(m.start(), m.end(), _plain(m.group())) for m in re.finditer(r"[^\W_]+", title)]
    spans = []
    for names in tag_names:
        words = _tag_words(names)
        strong = {w for w in words if len(w) >= 4 and w not in PARTICLES and w not in SUFFIXES}

        def belongs(w):
            return (w in words or any(_similar(w, x) for x in words if len(x) >= 6) or w in PARTICLES
                    or w in SUFFIXES or (len(w) == 1 and w.isalpha()))

        def is_strong(w):
            return w in strong or any(_similar(w, x) for x in strong if len(x) >= 6)

        i = 0
        while i < len(tokens):
            if not belongs(tokens[i][2]):
                i += 1
                continue
            j = i
            # a run: words next to each other, only spaces / dots between
            while j + 1 < len(tokens) and belongs(tokens[j + 1][2]) and \
                    re.fullmatch(r"[\s.]*", title[tokens[j][1]:tokens[j + 1][0]]):
                j += 1
            # Initials and particles only before a name: a run doesn't end
            # with one ("Beethoven I. Allegro" keeps its "I.").
            while j > i and ((len(tokens[j][2]) == 1 and tokens[j][2].isalpha()) or tokens[j][2] in PARTICLES):
                j -= 1
            if any(is_strong(t[2]) for t in tokens[i:j + 1]):
                end = tokens[j][1]
                if end < len(title) and title[end] == ".":
                    end += 1
                spans.append((tokens[i][0], end))
            i = j + 1
    if not spans:
        return tidy(title)
    # Overlapping stretches (two tags naming the same words) taken out as one.
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = title
    for a, b in reversed(merged):
        out = out[:a] + " " + out[b:]
    out = TRAILING_LINKS.sub("", tidy(out))
    out = tidy(out)
    return out or tidy(title)


def suggest_tags(gql, markers, settings):
    """Adds matching tags to the markers, and to every marker a
    "title_stripped": its title without its tags' names. Returns how many
    got a tag."""
    raw = (settings.get("suggestTagsUnder") or "").strip() or DEFAULT_SUGGEST_UNDER
    names = [n.strip() for n in raw.split(",") if n.strip() and n.strip() != "-"]
    for m in markers:
        m["title_stripped"] = strip_names(m["title"], [[t] for t in m["tags"]])
    if not names or not markers:
        return 0
    tags = tags_under(gql, names)
    if not tags:
        return 0
    matcher = TagMatcher(tags)
    known = {_plain(t["name"]) for t in tags}
    changed = 0
    for m in markers:
        before = list(m["tags"])
        kept = []
        for suggested in m["tags"]:
            hits = [] if _plain(suggested) in known else matcher.match(suggested)
            kept += hits or [suggested]
        kept += matcher.match(m["title"])
        m["tags"] = list(dict.fromkeys(kept))
        if m["tags"] != before:
            changed += 1
        aliases = {_plain(t["name"]): [t["name"], *(t.get("aliases") or [])] for t in tags}
        m["title_stripped"] = strip_names(m["title"], [aliases.get(_plain(t), [t]) for t in m["tags"]])
    return changed


# ---------------------------------------------------------------------------
# Composers in the titles of markers that already exist
# ---------------------------------------------------------------------------
#
# The same as for scraped markers (see suggest_tags), for the markers in
# Stash: every composer tag (under "Fill in tags under") named in a marker's
# title — whole name, alias or surname — is added to the marker, and the
# title loses the composers' names (also of composer tags it had already),
# with the separators and brackets they leave. Primary tag, times and other
# tags stay. "marker_composers" proposes the changes for one scene (args
# "scene_id") or every marker (no scene_id), and applies them with "apply":
# "true" — all, or only the markers in "ids" (a JSON list).

MARKER_FIELDS = "id title seconds scene { id title } primary_tag { id name } tags { id name }"


def find_markers(gql, scene_id=None):
    if scene_id:
        data = gql("query($id: ID!) { findScene(id: $id) { scene_markers { " + MARKER_FIELDS + " } } }", {"id": scene_id})
        return (data.get("findScene") or {}).get("scene_markers") or []
    data = gql("query { findSceneMarkers(filter: { per_page: -1 }) { scene_markers { " + MARKER_FIELDS + " } } }")
    return data["findSceneMarkers"]["scene_markers"]


def composer_proposals(gql, settings, scene_id=None):
    raw = (settings.get("suggestTagsUnder") or "").strip() or DEFAULT_SUGGEST_UNDER
    parents = [n.strip() for n in raw.split(",") if n.strip() and n.strip() != "-"]
    composers = tags_under(gql, parents) if parents else []
    if not composers:
        return [], f"No tags under {', '.join(parents) or '(none)'} — nothing to look for."
    matcher = TagMatcher(composers)
    by_name = {_plain(t["name"]) for t in composers} and {_plain(t["name"]): t for t in composers}
    proposals, missing = [], {}
    for m in find_markers(gql, scene_id):
        title = m.get("title") or ""
        if not title.strip():
            continue
        have = {_plain(t["name"]) for t in m.get("tags") or []}
        found = [by_name[_plain(n)] for n in matcher.match(title) if _plain(n) in by_name]
        if not found and not any(k in by_name for k in have):
            head = missing_composer(title)
            if head:
                missing[head] = missing.get(head, 0) + 1
        add = [t for t in found if _plain(t["name"]) not in have]
        named = found + [by_name[k] for k in have if k in by_name]
        new_title = strip_names(title, [[t["name"], *(t.get("aliases") or [])] for t in named]) if named else tidy(title)
        if not add and new_title == title:
            continue
        proposals.append({
            "id": str(m["id"]),
            "scene_id": str((m.get("scene") or {}).get("id") or ""),
            "scene": (m.get("scene") or {}).get("title") or "",
            "seconds": m.get("seconds"),
            "title": title,
            "new_title": new_title,
            "add_tags": [t["name"] for t in add],
            "add_tag_ids": [str(t["id"]) for t in add],
            "tag_ids": [str(t["id"]) for t in m.get("tags") or []],
        })
    proposals.sort(key=lambda p: (p["scene"], p["seconds"] or 0))
    composer_proposals.missing = [{"name": n, "count": c, "query": search_name(n)} for n, c in missing.items()]
    return proposals, ""


def missing_composer(title):
    """The name before the separator of a title that names no known composer
    — "Karl Komzak Sohn - Badner Madln" → "Karl Komzak Sohn" — if it looks
    like a person's name, else None."""
    m = re.match(r"^\s*(.+?)\s*(?:\s[-–—]\s|:\s|\s\|\s)", title or "")
    if not m:
        return None
    head = tidy(m.group(1))
    words = head.split()
    if not 2 <= len(words) <= 6 or re.search(r"\d|[()\[\]]", head):
        return None
    ok = all(w[:1].isupper() or w.lower().strip(".") in PARTICLES or w.lower().strip(".") in SUFFIXES for w in words)
    return head if ok else None


def search_name(name):
    """The name to search for: without Sohn / Vater / II / jr. …"""
    words = [w for w in name.split() if w.lower().strip(".") not in SUFFIXES or len(w) == 1]
    return " ".join(words) or name


def apply_composers(gql, proposals, only_ids=None, log=None):
    done = 0
    for p in proposals:
        if only_ids is not None and p["id"] not in only_ids:
            continue
        gql("mutation($input: SceneMarkerUpdateInput!) { sceneMarkerUpdate(input: $input) { id } }",
            {"input": {"id": p["id"], "title": p["new_title"], "tag_ids": list(dict.fromkeys(p["tag_ids"] + p["add_tag_ids"]))}})
        done += 1
        if log:
            log(f"{p['scene']} {p['seconds']:.0f}s: \"{p['title']}\" → \"{p['new_title']}\""
                + (f" + {', '.join(p['add_tags'])}" if p["add_tags"] else ""))
    return done


def marker_composers(gql, args, settings):
    proposals, note = composer_proposals(gql, settings, args.get("scene_id") or None)
    if str(args.get("apply", "false")).lower() != "true":
        return {"proposals": proposals, "notes": note, "missing": getattr(composer_proposals, "missing", [])}
    only = None
    if args.get("ids"):
        only = {str(i) for i in json.loads(args["ids"])}
    log = None
    if not args.get("scene_id"):  # the task: tell the log what changed
        log = lambda line: sys.stderr.write("\x01i\x02" + line + "\n")  # noqa: E731
    done = apply_composers(gql, proposals, only, log)
    return {"applied": done, "notes": note}


# ---------------------------------------------------------------------------
# Chapters waiting for a scene without markers
# ---------------------------------------------------------------------------
#
# For the page's offer to import them: the quick sources — a chapter file
# next to the video (also a medici.tv JSON), the video's own chapters, and
# ARTE / ORF ON through the scene's URLs — are tried, and those that find two
# or more chapters (with different starts) are reported. Nothing is created.

#
# With "all" (the Scrape markers… menu, also for scenes with markers), the
# subtitles next to / in the video are tried too, and every scraper tried
# is reported in "checked" — {id: {"count", "why"}} — so the menu can turn
# off those that find nothing, and say why.

QUICK_SCRAPERS = ("chapter_files", "video_chapters", "arte", "orf")
MENU_SCRAPERS = QUICK_SCRAPERS + ("subtitles",)
QUICK_TIMEOUT = 60


def available(gql, args, settings, env_extra):
    scene = scene_for_scraper(gql, args.get("scene_id"))
    if not scene:
        return {"found": [], "checked": {}}
    everything = bool(args.get("all"))
    if scene.get("scene_markers") and not everything:
        return {"found": [], "has_markers": True}
    scrapers = load_scrapers(settings)
    urls = scene.get("urls") or []
    found, checked = [], {}
    for sid in (MENU_SCRAPERS if everything else QUICK_SCRAPERS):
        scraper = scrapers.get(sid)
        if not scraper or not scraper["fragment"]:
            continue
        if scraper["by_url"] and not scraper["fragment_in_menu"] and not any(any(p in u for p in url_patterns(scraper)) for u in urls):
            checked[sid] = {"count": 0, "why": "the scene has no URL of this site"}
            continue  # a scraper for websites, and the scene has none of its URLs
        action = dict(scraper["fragment"], timeout=min(int(scraper["fragment"].get("timeout") or QUICK_TIMEOUT), QUICK_TIMEOUT))
        try:
            markers, notes, _pieces = run_action(scraper, action, {"scene": scene, "quick": True}, env_extra)
        except RuntimeError as exc:
            # A scraper that says why it found nothing ("No chapter file next
            # to the video …") is turned off with that; one that crashed isn't.
            why = str(exc).split(" failed: ", 1)[-1].strip()
            if " failed: " in str(exc) and why and "Traceback" not in why:
                checked[sid] = {"count": 0, "why": why[-300:]}
            continue
        except Exception:  # noqa: BLE001 — timed out or can't tell: not offered, not turned off
            continue
        markers = normalise(markers)
        checked[sid] = {"count": len(markers), "why": "" if markers else (notes or f"{scraper['name']}: nothing found")}
        if sid in QUICK_SCRAPERS and len(markers) >= 2 and len({m["seconds"] for m in markers}) > 1:
            found.append({"scraper": sid, "name": scraper["name"], "count": len(markers), "notes": notes})
    # Subtitles made for exactly this file on OpenSubtitles (a search by its
    # fingerprint — no download), when an API key is set.
    if env_extra.get("OS_API_KEY") and "opensubtitles" in scrapers:
        try:
            os.environ.update(env_extra)
            sys.path.insert(0, BUILT_IN_DIR)
            import subtitles
            exact = subtitles.exact_match(scene)
        except Exception:  # noqa: BLE001
            exact = []
        if exact:
            langs = sorted({(s.get("attributes") or {}).get("language") or "?" for s in exact})
            found.append({"scraper": "opensubtitles", "name": scrapers["opensubtitles"]["name"], "count": None,
                          "label": f"subtitles made for exactly this file ({', '.join(langs)})", "notes": ""})
            checked["opensubtitles"] = {"count": None, "why": "", "label": f"made for this file ({', '.join(langs)})"}
    elif "opensubtitles" in scrapers:
        checked["opensubtitles"] = {"count": 0, "why": "no API key in the plugin's settings", "setup": True}
    # Text in the picture: not tried here (it reads the whole video), only
    # whether tesseract is there.
    if everything and "frames_ocr" in scrapers:
        tesseract = env_extra.get("TESSERACT") or "tesseract"
        if not (shutil.which(tesseract) or os.path.isfile(tesseract)):
            checked["frames_ocr"] = {"count": 0, "setup": True, "why":
                                     "tesseract isn't installed on the Stash server (apt install tesseract-ocr tesseract-ocr-deu)"}
    if scene.get("scene_markers"):
        found = []  # not offered for a scene with markers — the menu only
    return {"found": found, "checked": checked}


# ---------------------------------------------------------------------------
# Plugin entry point (Stash runs this with interface: raw)
# ---------------------------------------------------------------------------

# How far a long scraper is (Text in the picture writes it): read by the
# dialog every few seconds while it waits.
def scrape_progress(args):
    sys.path.insert(0, BUILT_IN_DIR)
    import storage
    name = re.sub(r"\W", "", str(args.get("scene_id") or ""))
    try:
        with open(os.path.join(storage.folder("progress"), f"{name}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def make_gql(server_connection):
    scheme = server_connection.get("Scheme", "http")
    host = server_connection.get("Host") or "localhost"
    if host in ("0.0.0.0", ""):
        host = "localhost"
    url = f"{scheme}://{host}:{server_connection.get('Port', 9999)}/graphql"
    headers = {"Content-Type": "application/json"}
    cookie = server_connection.get("SessionCookie") or {}
    if cookie.get("Name") and cookie.get("Value"):
        headers["Cookie"] = f"{cookie['Name']}={cookie['Value']}"
    api_key = server_connection.get("ApiKey") or os.environ.get("STASH_API_KEY")
    if api_key:
        headers["ApiKey"] = api_key

    def gql(query, variables=None):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode())
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL error: {payload['errors']}")
        return payload["data"]

    return gql


def tool_paths(gql):
    """(settings of this plugin, environment for scraper scripts)."""
    try:
        plugins = gql("query { configuration { plugins } }")["configuration"]["plugins"] or {}
    except Exception:  # noqa: BLE001
        plugins = {}
    old = plugins.get(OLD_PLUGIN_ID) or {}
    settings = {**{k: old[k] for k in SETTING_KEYS if old.get(k)}, **(plugins.get(PLUGIN_ID) or {})}
    ytdlp = (settings.get("ytdlpPath") or "").strip() \
        or ((plugins.get("advancedFileOperations") or {}).get("ytdlpPath") or "").strip() \
        or "yt-dlp"
    try:
        general = gql("query { configuration { general { ffmpegPath ffprobePath generatedPath } } }")["configuration"]["general"]
    except Exception:  # noqa: BLE001
        general = {}
    return settings, {
        "STASH_FFMPEG": general.get("ffmpegPath") or "ffmpeg",
        "STASH_FFPROBE": general.get("ffprobePath") or "ffprobe",
        # the analyses go to Stash's generated folder; made absolute here — the
        # plugin runs in Stash's working directory, the scrapers in their own
        "STASH_GENERATED": os.path.abspath(general["generatedPath"]) if general.get("generatedPath") else "",
        "STASH_YTDLP": ytdlp,
        # the Subtitles from OpenSubtitles scraper
        "OS_API_KEY": str(settings.get("openSubtitlesApiKey") or ""),
        "OS_USERNAME": str(settings.get("openSubtitlesUser") or ""),
        "OS_PASSWORD": str(settings.get("openSubtitlesPassword") or ""),
        "OS_LANGUAGES": str(settings.get("openSubtitlesLanguages") or "de,en"),
        # Text in the picture (OCR)
        "TESSERACT": str(settings.get("tesseractPath") or ""),
        "OCR_LANGUAGES": str(settings.get("ocrLanguages") or settings.get("openSubtitlesLanguages") or "de,en"),
        "OCR_EXPLICIT": "1" if str(settings.get("ocrLanguages") or "").strip() else "",
    }


def main():
    raw = sys.stdin.read()
    plugin_input = json.loads(raw) if raw.strip() else {}
    args = plugin_input.get("args") or {}
    try:
        gql = make_gql(plugin_input.get("server_connection") or {})
        settings, env_extra = tool_paths(gql)
        mode = args.get("mode")
        if mode == "marker_scrapers_list":
            output = list_scrapers(settings)
        elif mode == "marker_scrape":
            output = scrape(gql, args, settings, env_extra)
        elif mode == "marker_available":
            output = available(gql, args, settings, env_extra)
        elif mode == "marker_ocr_job":
            # Text in the picture, as a task in Stash's job queue
            os.environ.update(env_extra)
            sys.path.insert(0, BUILT_IN_DIR)
            import frames_ocr
            scene = scene_for_scraper(gql, args.get("scene_id"))
            if not scene:
                raise ValueError(f"No scene {args.get('scene_id')}.")
            answer = frames_ocr.run_job(scene, lambda line: sys.stderr.write("\x01i\x02" + line + "\n"))
            output = {"markers": len(answer["markers"])}
        elif mode == "marker_progress":
            os.environ.update(env_extra)
            output = scrape_progress(args)
        elif mode in ("marker_files", "marker_align", "marker_record", "marker_hook", "marker_remember_all"):
            os.environ.update(env_extra)
            import marker_files
            if mode == "marker_files":
                output = marker_files.files_of(gql, args.get("scene_id"))
            elif mode == "marker_align":
                ids = [i for i in str(args.get("marker_ids") or "").split(",") if i]
                output = marker_files.align(gql, args.get("scene_id"), args.get("from_file"), ids or None,
                                            args.get("method") or "audio")
            elif mode == "marker_record":
                ids = [i for i in str(args.get("marker_ids") or "").split(",") if i]
                seconds = [float(x) for x in str(args.get("seconds") or "").split(",") if x]
                marker_files.record({i: (args.get("file_id"), s) for i, s in zip(ids, seconds)})
                output = {"recorded": len(ids)}
            elif mode == "marker_hook":
                marker_files.hook(gql, args.get("hookContext") or {})
                output = None
            else:
                output = marker_files.remember_all(gql, lambda line: sys.stderr.write("\x01i\x02" + line + "\n"))
        elif mode == "marker_composers":
            output = marker_composers(gql, args, settings)
            if not args.get("scene_id") and "applied" in output:
                sys.stderr.write(f"\x01i\x02Composers from marker titles: {output['applied']} markers changed.\n")
        elif mode == "marker_pauses":
            os.environ.update(env_extra)
            sys.path.insert(0, BUILT_IN_DIR)
            import pauses
            try:
                output = pauses.check(scene_for_scraper(gql, args.get("scene_id")) or {})
            except SystemExit as exc:  # pauses' "can't" messages
                raise RuntimeError(str(exc)) from None
        else:
            raise ValueError(f"Unknown mode: {mode}")
        print(json.dumps({"output": output}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))


if __name__ == "__main__":
    main()
