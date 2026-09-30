#!/usr/bin/env python3
"""
yt-dlp Downloader — a Stash plugin.

Downloads videos (or whole playlists) with yt-dlp into one of your Stash
library folders, then fills in each new scene from the video's own info:
title, source URL, upload date, description, and its thumbnail as cover.

Modes (the "mode" arg):
  - download: runs yt-dlp for the given URLs, then queues a scan of the new
    files and a "finalize" task behind it. Stash runs one task at a time,
    so the scan can't start while this task runs — the finalize task,
    queued after the scan, finds the scenes it created.
  - finalize: fills in the new scenes, then removes the downloaded info
    and thumbnail files, which were kept in a temporary folder so they
    never land in your library.
  - download with background=true: the same, but detached from Stash's
    task queue (see start_in_background).

Needs yt-dlp on the server (apt install yt-dlp, or pip install yt-dlp) and
ffmpeg for merging video and audio. Standard library only otherwise.
"""

import base64
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

# Stash's id for this plugin — the yml manifest's filename minus ".yml".
# Must match PLUGIN_ID in ytdlp-ui.js.
PLUGIN_ID = "ytdlpDownloader"

# yt-dlp format selections for the dialog's quality choices. "bv*+ba"
# picks the best video and best audio stream and merges them; "/b" falls
# back to the best single file with both.
FORMATS = {
    "best": "bv*+ba/b",
    "2160": "bv*[height<=2160]+ba/b[height<=2160]/b",
    "1080": "bv*[height<=1080]+ba/b[height<=1080]/b",
    "720": "bv*[height<=720]+ba/b[height<=720]/b",
}

# Where downloaded files go, inside the chosen folder. %(title).150B keeps
# long titles to 150 bytes, so paths stay within filesystem limits.
OUTPUT_TEMPLATE = "%(title).150B [%(id)s].%(ext)s"

_PROGRESS_RE = re.compile(r"\[progress\]\s+([\d.]+)%")
_RESULT_PREFIX = "[result]\t"

# Background runs (see start_in_background) write readable log lines.
BACKGROUND = False
_LEVEL_NAMES = {"t": "TRACE", "d": "DEBUG", "i": "INFO", "w": "WARN", "e": "ERROR", "p": "PROGRESS"}
_last_background_progress = -1


# ---------------------------------------------------------------------------
# Stash plugin log protocol: SOH, level letter, STX, message.
# ---------------------------------------------------------------------------

def _log(level, message):
    global _last_background_progress
    if BACKGROUND:
        if level == "p":
            step = int(float(message) * 100) // 5
            if step == _last_background_progress:
                return
            _last_background_progress = step
            message = f"{step * 5}%"
        sys.stderr.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{_LEVEL_NAMES.get(level, level)}] {message}\n")
    else:
        sys.stderr.write(f"\x01{level}\x02{message}\n")
    sys.stderr.flush()


def log_info(message):
    _log("i", message)


def log_warn(message):
    _log("w", message)


def log_error(message):
    _log("e", message)


def log_progress(fraction):
    _log("p", f"{max(0.0, min(1.0, fraction)):.4f}")


def write_plugin_output(output=None, error=None):
    print(json.dumps({"error": str(error)} if error else {"output": output or "ok"}))


# ---------------------------------------------------------------------------
# Stash GraphQL (stdlib only)
# ---------------------------------------------------------------------------

class Stash:
    def __init__(self, server_connection):
        scheme = server_connection.get("Scheme", "http")
        host = server_connection.get("Host") or "localhost"
        if host in ("0.0.0.0", ""):
            host = "localhost"
        port = server_connection.get("Port", 9999)
        self.url = f"{scheme}://{host}:{port}/graphql"
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        cookie = server_connection.get("SessionCookie") or {}
        if cookie.get("Name") and cookie.get("Value"):
            self.headers["Cookie"] = f"{cookie['Name']}={cookie['Value']}"
        api_key = server_connection.get("ApiKey") or os.environ.get("STASH_API_KEY")
        if api_key:
            self.headers["ApiKey"] = api_key

    def call(self, query, variables=None):
        body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST", headers=self.headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} from Stash: {exc.read()[:500]!r}") from exc
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL error: {payload['errors']}")
        return payload["data"]

    def plugin_settings(self):
        try:
            data = self.call("query { configuration { plugins } }")
            return (data["configuration"].get("plugins") or {}).get(PLUGIN_ID) or {}
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Couldn't read plugin settings, using defaults: {exc}")
            return {}

    def scan(self, paths):
        """Queues a scan of `paths` that also generates covers and phashes."""
        options = {"paths": paths, "scanGenerateCovers": True, "scanGeneratePhashes": True}
        try:
            self.call("mutation($input: ScanMetadataInput!) { metadataScan(input: $input) }", {"input": options})
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Scan with covers/phashes failed ({exc}); scanning without them")
            self.call("mutation($paths: [String!]) { metadataScan(input: { paths: $paths }) }", {"paths": paths})

    def run_plugin_task(self, description, args_map):
        self.call(
            "mutation($plugin_id: ID!, $description: String, $args_map: Map) "
            "{ runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map) }",
            {"plugin_id": PLUGIN_ID, "description": description, "args_map": args_map},
        )

    def find_scene_by_path(self, path):
        try:
            data = self.call(
                "query($path: String!) { findScenes(scene_filter: { path: { value: $path, modifier: EQUALS } }, "
                "filter: { per_page: 1 }) { scenes { id } } }",
                {"path": path},
            )
            scenes = data["findScenes"]["scenes"]
            if scenes:
                return scenes[0]["id"]
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Path lookup failed ({exc}); checking the newest scenes instead")
        data = self.call(
            "query { findScenes(filter: { per_page: 100, sort: \"created_at\", direction: DESC }) "
            "{ scenes { id files { path } } } }"
        )
        for scene in data["findScenes"]["scenes"]:
            if any(f.get("path") == path for f in scene.get("files") or []):
                return scene["id"]
        return None

    def update_scene(self, scene_input):
        mutation = "mutation($input: SceneUpdateInput!) { sceneUpdate(input: $input) { id } }"
        try:
            self.call(mutation, {"input": scene_input})
        except Exception as exc:  # noqa: BLE001
            if "urls" not in scene_input:
                raise
            # Stash before v0.24 has a single `url` instead of `urls`.
            log_warn(f"Scene update with urls failed ({exc}); retrying with a single url")
            fallback = {k: v for k, v in scene_input.items() if k != "urls"}
            fallback["url"] = scene_input["urls"][0]
            self.call(mutation, {"input": fallback})


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------

def ytdlp_command(settings):
    path = (settings.get("ytdlpPath") or "").strip() or "yt-dlp"
    return shlex.split(path)


def run_download(stash, args):
    urls = [u.strip() for u in (args.get("urls") or "").splitlines() if u.strip()]
    dest = (args.get("dest") or "").strip()
    subfolder = (args.get("subfolder") or "").strip().strip("/\\")
    quality = args.get("quality") or "best"
    if not urls:
        write_plugin_output(error="No URL given")
        return
    if not dest or not os.path.isdir(dest):
        write_plugin_output(error=f"Destination folder doesn't exist on the server: {dest!r}")
        return
    if subfolder:
        if ".." in subfolder.replace("\\", "/").split("/"):
            write_plugin_output(error="The subfolder can't contain '..'")
            return
        dest = os.path.join(dest, subfolder)
        os.makedirs(dest, exist_ok=True)

    settings = stash.plugin_settings()
    # Info and thumbnail files go to a temporary folder, not the library:
    # otherwise Stash's scan would pick the thumbnails up as images.
    sidecar_dir = tempfile.mkdtemp(prefix="ytdlp-stash-")

    cmd = ytdlp_command(settings) + [
        "--format", FORMATS.get(quality, FORMATS["best"]),
        "--merge-output-format", "mp4",
        "--paths", dest,
        "--output", OUTPUT_TEMPLATE,
        "--output", f"infojson:{sidecar_dir}/%(id)s.%(ext)s",
        "--output", f"thumbnail:{sidecar_dir}/%(id)s.%(ext)s",
        "--write-info-json",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "--no-simulate",
        "--print", f"after_move:{_RESULT_PREFIX}%(id)s\t%(filepath)s",
        "--progress", "--newline",
        "--progress-template", "download:[progress] %(progress._percent_str)s",
    ]
    cookies = (settings.get("cookiesFile") or "").strip()
    if cookies:
        cmd += ["--cookies", cookies]
    extra = (settings.get("extraArgs") or "").strip()
    if extra:
        cmd += shlex.split(extra)

    results = []
    failed = []
    for index, url in enumerate(urls):
        log_info(f"Downloading {index + 1}/{len(urls)}: {url}")
        base = index / len(urls)
        try:
            proc = subprocess.Popen(
                cmd + ["--", url], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except FileNotFoundError:
            shutil.rmtree(sidecar_dir, ignore_errors=True)
            write_plugin_output(
                error="yt-dlp wasn't found on the server. Install it (Debian: apt install yt-dlp, "
                      "or pip install yt-dlp), or set its path in the plugin's settings."
            )
            return
        tail = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line.startswith(_RESULT_PREFIX):
                video_id, _, filepath = line[len(_RESULT_PREFIX):].partition("\t")
                results.append({"id": video_id, "path": filepath, "pasted_url": url})
                log_info(f"Downloaded {os.path.basename(filepath)}")
                continue
            match = _PROGRESS_RE.search(line)
            if match:
                log_progress(base + float(match.group(1)) / 100 / len(urls))
                continue
            if line.strip():
                tail = (tail + [line])[-15:]
                if "ERROR" in line or "WARNING" in line:
                    log_warn(line)
        if proc.wait() != 0:
            failed.append(url)
            log_error(f"yt-dlp failed for {url}:\n" + "\n".join(tail))

    log_progress(1.0)
    if not results:
        shutil.rmtree(sidecar_dir, ignore_errors=True)
        write_plugin_output(error=f"Nothing was downloaded ({len(failed)} URL(s) failed — see the log above).")
        return

    # Pair each file with its info and thumbnail by the video's id, and the
    # URL that was pasted to get it.
    items = []
    for r in results:
        info = os.path.join(sidecar_dir, f"{r['id']}.info.json")
        thumb = os.path.join(sidecar_dir, f"{r['id']}.jpg")
        items.append([
            r["path"],
            info if os.path.isfile(info) else "",
            thumb if os.path.isfile(thumb) else "",
            r["pasted_url"],
        ])

    log_info("Queueing a scan of the new files, then a task to fill in their scenes...")
    paths = [item[0] for item in items]
    stash.scan(sorted({os.path.dirname(p) for p in paths}) if len(items) > 20 else paths)
    try:
        stash.run_plugin_task(
            f"Finish downloads ({len(items)} video{'s' if len(items) != 1 else ''})",
            {"mode": "finalize", "items": json.dumps(items), "sidecar_dir": sidecar_dir},
        )
    except Exception as exc:  # noqa: BLE001
        write_plugin_output(
            error=f"Downloaded {len(items)} video(s) and queued a scan, but couldn't queue the task that fills "
                  f"in their scenes ({exc}). The files are there; their scenes just won't have titles etc."
        )
        return

    summary = f"Downloaded {len(items)} video(s)"
    if failed:
        summary += f", {len(failed)} URL(s) failed"
    summary += ". Their scenes are filled in by the \"Finish downloads\" task right after the scan."
    log_info(summary)
    write_plugin_output(output=summary)


# ---------------------------------------------------------------------------
# Filling in the new scenes
# ---------------------------------------------------------------------------

def scene_input_from_info(scene_id, info, thumb_path, pasted_url=""):
    scene = {"id": scene_id}
    if info.get("title"):
        scene["title"] = info["title"]
    # The video's canonical page when yt-dlp knows it; otherwise the URL
    # that was pasted to get it, so the scene always links to its source.
    url = info.get("webpage_url") or info.get("original_url") or pasted_url
    if url:
        scene["urls"] = [url]
    raw_date = info.get("release_date") or info.get("upload_date") or ""
    if re.fullmatch(r"\d{8}", raw_date):
        scene["date"] = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    if info.get("description"):
        scene["details"] = info["description"]
    if thumb_path:
        with open(thumb_path, "rb") as f:
            scene["cover_image"] = "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")
    return scene


def run_finalize(stash, args):
    try:
        items = json.loads(args.get("items") or "[]")
    except ValueError as exc:
        write_plugin_output(error=f"finalize got an invalid items argument: {exc}")
        return
    done, missing = 0, 0
    for index, item in enumerate(items, start=1):
        # [path, info, thumbnail, pasted URL] — the pasted URL is missing in
        # tasks queued by version 0.0.1 of this plugin.
        path, info_path, thumb_path = item[:3]
        pasted_url = item[3] if len(item) > 3 else ""
        log_progress((index - 1) / max(len(items), 1))
        scene_id = stash.find_scene_by_path(path)
        if not scene_id:
            missing += 1
            log_warn(f"Couldn't find the scene for {os.path.basename(path)} — is its folder one of your library paths?")
            continue
        info = {}
        if info_path:
            try:
                with open(info_path, encoding="utf-8") as f:
                    info = json.load(f)
            except (OSError, ValueError) as exc:
                log_warn(f"Couldn't read the info for {os.path.basename(path)}: {exc}")
        try:
            stash.update_scene(scene_input_from_info(scene_id, info, thumb_path, pasted_url))
            done += 1
            log_info(f"Filled in scene {scene_id}: {info.get('title') or os.path.basename(path)}")
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Couldn't fill in scene {scene_id} ({os.path.basename(path)}): {exc}")

    sidecar_dir = args.get("sidecar_dir") or ""
    # Only ever remove a folder this plugin made.
    if os.path.basename(sidecar_dir).startswith("ytdlp-stash-"):
        shutil.rmtree(sidecar_dir, ignore_errors=True)

    log_progress(1.0)
    summary = f"Filled in {done} of {len(items)} downloaded scene(s)."
    if missing:
        summary += f" {missing} scene(s) weren't found — see the warnings above."
    log_info(summary)
    write_plugin_output(output=summary)


# ---------------------------------------------------------------------------
# Background runs
# ---------------------------------------------------------------------------

def start_in_background(plugin_input):
    """
    Runs this same script again detached from Stash, then returns at once,
    so a long download doesn't hold up Stash's one-at-a-time task queue.
    Its log goes to a file in a "logs" folder next to this script.
    """
    args = dict(plugin_input.get("args") or {})
    args.pop("background", None)
    args["_background_child"] = "true"

    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        if not os.access(log_dir, os.W_OK):
            raise OSError("not writable")
    except OSError:
        log_dir = tempfile.gettempdir()
    log_path = os.path.join(log_dir, f"ytdlp-{time.strftime('%Y%m%d-%H%M%S')}.log")

    if os.name == "nt":
        detach = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
        stop = "taskkill /T /F /PID {pid}"
    else:
        detach = {"start_new_session": True}
        stop = "kill -- -{pid}"
    with open(log_path, "w") as log_file:
        proc = subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            stdin=subprocess.PIPE, stdout=log_file, stderr=log_file, close_fds=True, text=True, **detach,
        )
    proc.stdin.write(json.dumps({**plugin_input, "args": args}))
    proc.stdin.close()
    stop = stop.format(pid=proc.pid)
    log_info(f"Downloading in the background as process {proc.pid}. Log: {log_path}")
    write_plugin_output(output=f"Downloading in the background (process {proc.pid}). Log: {log_path} — stop it with: {stop}")


def main():
    global BACKGROUND
    raw = sys.stdin.read()
    plugin_input = json.loads(raw) if raw.strip() else {}
    args = plugin_input.get("args") or {}
    if str(args.get("background", "false")).lower() == "true":
        start_in_background(plugin_input)
        return
    BACKGROUND = str(args.get("_background_child", "false")).lower() == "true"

    stash = Stash(plugin_input.get("server_connection") or {})
    mode = args.get("mode")
    if mode == "download":
        run_download(stash, args)
    elif mode == "finalize":
        run_finalize(stash, args)
    else:
        write_plugin_output(error="Start a download from the download button in Stash's top bar.")


if __name__ == "__main__":
    main()
