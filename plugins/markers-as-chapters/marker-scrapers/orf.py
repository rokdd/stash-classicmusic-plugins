"""Marker scraper: the segments of an ORF ON video.

stdin: {"scene": {...}, "url": optional}
stdout: {"markers": [...], "notes": "..."}

ORF ON (on.orf.at, formerly the TVthek) splits a broadcast into segments —
a concert usually into its pieces, with their titles. The episode is the
segments one after the other, so each starts where the one before it
ends (their exact lengths, in milliseconds, add up to the episode's).
Read from ORF's public API, as its player does (the episode id encoded as
the player encodes it). ORF ON keeps videos only for a while; after that
there are no segments to read. Without "url" the scene's ORF URL is used.
"""

import base64
import json
import re
import sys
import urllib.request

API = "https://api-tvthek.orf.at/api/v4.3/public/episode/encrypted/{}"


def episode_id(url):
    m = re.search(r"on\.orf\.at/video/(\d+)", url)
    if m:
        return m.group(1)
    if "tvthek.orf.at" in url:
        # /profile/<name>/<profile id>/<episode name>/<episode id>[/<segment name>/<segment id>]
        numbers = re.findall(r"/(\d{5,10})(?=/|$|\?)", url)
        return numbers[1] if len(numbers) > 1 else (numbers[0] if numbers else None)
    return None


def fetch(episode):
    encoded = base64.b64encode(f"3dSlfek03nsLKdj4Jsd{episode}".encode()).decode()
    request = urllib.request.Request(API.format(encoded), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    payload = json.load(sys.stdin)
    scene = payload.get("scene") or {}
    urls = [payload["url"]] if payload.get("url") else [u for u in scene.get("urls") or [] if "orf.at" in u]
    if not urls:
        raise SystemExit("The scene has no ORF ON URL — use “other URL…” to enter one (on.orf.at/video/…).")
    episode = episode_id(urls[0])
    if not episode:
        raise SystemExit(f"No ORF ON video id in {urls[0]} (expected on.orf.at/video/<number>).")
    try:
        data = fetch(episode)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(f"ORF ON doesn't have video {episode} (any more) — it keeps videos only for a while.")
        raise
    segments = sorted(((data.get("_embedded") or {}).get("segments") or []), key=lambda s: s.get("position") or 0)
    if not segments:
        print(json.dumps({"markers": [], "notes": "ORF ON has no segments for this video (any more)."}))
        return
    if len(segments) == 1:
        print(json.dumps({"markers": [], "notes": "ORF ON doesn't split this video into pieces — it's one segment."}))
        return
    markers, start = [], 0.0
    for s in segments:
        length = (s.get("exact_duration") or (s.get("duration_seconds") or 0) * 1000) / 1000
        title = (s.get("title") or s.get("headline") or "").strip()
        markers.append({"seconds": round(start, 3), "end_seconds": round(start + length, 3) if length else None,
                        "title": title})
        start += length
    total = (data.get("exact_duration") or 0) / 1000
    notes = f"{len(markers)} segments of “{data.get('title', '')}” on ORF ON."
    if total and abs(total - start) > 2:
        notes += f" Their lengths add up to {start:.0f} s, the video's to {total:.0f} s — check the times."
    print(json.dumps({"markers": markers, "notes": notes}))


if __name__ == "__main__":
    main()
