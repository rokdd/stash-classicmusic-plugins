"""
Marker scrapers — part of the Marker Improvements plugin (its Python side;
everything it needs is in this plugin).

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

(only "seconds" is required). Scripts run in their scraper's folder, with
the environment variables STASH_FFPROBE (Stash's own ffprobe) and
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
Standard library only.
"""

import json
import os
import re
import subprocess
import sys
import urllib.request

PLUGIN_ID = "markerImprovements"

BUILT_IN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marker-scrapers")
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
                    "dir": root,
                    "fragment": config.get("markerByFragment"),
                    "by_url": by_url,
                    "by_text": config.get("markerByText"),
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
         "text": bool(s["by_text"])}
        for s in sorted(load_scrapers(settings).values(), key=lambda s: s["name"].lower())
    ]


# ---------------------------------------------------------------------------
# Running one
# ---------------------------------------------------------------------------

def scene_for_scraper(gql, scene_id):
    data = gql(
        "query($id: ID!) { findScene(id: $id) { id title code details date urls "
        "files { path duration } scene_markers { seconds end_seconds title } } }",
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
        cwd=scraper["dir"], env=env, timeout=SCRIPT_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Scraper {scraper['name']} failed: {(proc.stderr or proc.stdout)[-800:]}")
    try:
        result = json.loads(proc.stdout or "[]")
    except ValueError as exc:
        raise RuntimeError(f"Scraper {scraper['name']} didn't print JSON: {exc}") from exc
    return result if isinstance(result, list) else result.get("markers", [])


def normalise(markers):
    out = []
    for m in markers:
        if not isinstance(m, dict) or m.get("seconds") is None:
            continue
        tags = m.get("tags") or []
        out.append({
            "seconds": round(float(m["seconds"]), 3),
            "end_seconds": round(float(m["end_seconds"]), 3) if m.get("end_seconds") is not None else None,
            "title": str(m.get("title") or ""),
            "primary_tag": str(m.get("primary_tag") or ""),
            "tags": [str(t) for t in (tags if isinstance(tags, list) else [tags]) if t],
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
    markers = normalise(run_action(scraper, action, payload, env_extra))
    return {"scraper": scraper["name"], "markers": markers, "existing": scene.get("scene_markers") or []}


# ---------------------------------------------------------------------------
# Plugin entry point (Stash runs this with interface: raw)
# ---------------------------------------------------------------------------

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
    settings = plugins.get(PLUGIN_ID) or {}
    ytdlp = (settings.get("ytdlpPath") or "").strip() \
        or ((plugins.get("advancedFileOperations") or {}).get("ytdlpPath") or "").strip() \
        or "yt-dlp"
    try:
        ffprobe = gql("query { configuration { general { ffprobePath } } }")["configuration"]["general"]["ffprobePath"] or ""
    except Exception:  # noqa: BLE001
        ffprobe = ""
    return settings, {"STASH_FFPROBE": ffprobe or "ffprobe", "STASH_YTDLP": ytdlp}


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
        else:
            raise ValueError(f"Unknown mode: {mode}")
        print(json.dumps({"output": output}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}))


if __name__ == "__main__":
    main()
