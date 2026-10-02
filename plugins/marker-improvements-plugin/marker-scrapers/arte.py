"""Marker scraper: the chapters of an arte.tv video.

stdin: {"scene": {...}, "url": optional}  → stdout: a JSON list of markers.
Without "url" it uses the scene's arte.tv URL. Reads arte's player API
(api.arte.tv/api/player/v2/config/<language>/<program id>), the same
data arte's own player shows its chapters from. Each chapter ends where
the next starts, the last at the end of the video. ARTE Concert chapters
name composer and performers in their titles: those are suggested as
tags (used when you have a tag of that name or alias, see suggested_tags).
Some videos have no chapters at arte — then nothing is found; the plain
text scraper with the program from the description is the way then."""

import json
import re
import sys
import urllib.request

API = "https://api.arte.tv/api/player/v2/config/{lang}/{program}"


def program_of(url):
    m = re.search(r"arte\.tv/(?P<lang>[a-z]{2})/videos/(?P<program>\d{6}-\d{3}-[A-Z])", url, re.I) \
        or re.search(r"(?P<program>\d{6}-\d{3}-[A-Z])", url)
    if not m:
        return None
    lang = (m.groupdict().get("lang") or "de").lower()
    return lang, m.group("program").upper()


NAME_RE = re.compile(r"^[^\d:;()\[\]]{3,60}$")


def suggested_tags(title):
    """Names from a chapter title, as tag suggestions. ARTE Concert writes
    "Composer - Work", "Composer, Work" or "Orchestra : Composer - Work";
    a part counts as a name when it's short and has no digits. Only names
    you have tags for are used, so a wrong guess costs nothing."""
    tags = []
    performer, sep, rest = title.partition(" : ")
    if not sep:
        rest = title
    elif NAME_RE.match(performer.strip()):
        tags.append(performer.strip())
    composer, sep, _work = rest.partition(" - ")
    if not sep:
        composer, sep, _work = rest.partition(", ")
    composer = composer.strip()
    if sep and NAME_RE.match(composer) and len(composer.split()) <= 5:
        tags.append(composer)
    return tags


def fetch(lang, program):
    req = urllib.request.Request(API.format(lang=lang, program=program), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["data"]["attributes"]


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    urls = [payload["url"]] if payload.get("url") else [u for u in scene.get("urls") or [] if "arte.tv" in u]
    if not urls:
        raise SystemExit("The scene has no arte.tv URL — use \"other URL…\" to enter one.")
    found = program_of(urls[0])
    if not found:
        raise SystemExit(f"No arte program id (like 132137-000-A) in {urls[0]}")
    attrs = fetch(*found)
    chapters = sorted(((attrs.get("chapters") or {}).get("elements") or []), key=lambda c: c.get("startTime") or 0)
    duration = ((attrs.get("metadata") or {}).get("duration") or {}).get("seconds")
    markers = []
    for i, c in enumerate(chapters):
        start = float(c.get("startTime") or 0)
        end = float(chapters[i + 1].get("startTime") or 0) if i + 1 < len(chapters) else duration
        title = (c.get("title") or "").strip() or f"Chapter {i + 1}"
        markers.append({
            "seconds": start,
            "end_seconds": float(end) if end and float(end) > start else None,
            "title": title,
            "tags": suggested_tags(title),
        })
    print(json.dumps(markers))


if __name__ == "__main__":
    main()
