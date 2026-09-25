#!/usr/bin/env python3
"""
Advanced File Operations — a Stash plugin.

Three video tools for your Stash library:
  - H265 conversion: re-encodes non-HEVC video to H.265 at a chosen
    quality (a preset or custom CRF), per-scene or across the whole
    library. Per-scene, with "keep original" checked (the default), the
    source file is never deleted — the new file is attached to the same
    scene and set as its primary file, original kept as a secondary file.
  - Split at markers: cuts a scene's file into one new scene per chosen
    marker, carrying metadata and markers into each part.
  - Repair: detects corrupt files and fixes them, lossless remux first,
    tolerant re-encode as a fallback.

Install:
    1. Copy this whole folder into your Stash "plugins" directory
       (Settings > Plugins will show you the path, usually ~/.stash/plugins).
    2. Make sure `ffmpeg` (with libx265 support) is on the PATH Stash's
       process uses. If Stash bundles its own ffmpeg, point FFMPEG_BIN
       below at it, e.g. the path shown in Settings > System.
    3. `pip install requests` in the Python environment Stash calls
       (see requirements.txt).
    4. Reload plugins in Settings > Plugins. The H265 library tasks show
       up under Settings > Tasks > Plugin Tasks; a "File Operations" menu
       (Convert to H265 / Split at Markers / Repair File) shows up on each
       scene's page.

Notes on "without losing quality":
    H.265 is a lossy codec, so *some* generation loss versus the source is
    unavoidable — there is no way to change codecs with zero loss unless the
    source is already lossless (which video files essentially never are).
    What this plugin gives you is "visually lossless": a CRF of 18 is
    generally indistinguishable from the source to the eye, at a noticeably
    smaller file size than H.264 at an equivalent quality. Lower CRF_VALUE
    below for even closer-to-source quality (larger files); raise it for
    smaller files at a small, usually-invisible quality cost.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import requests

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# x265 CRF: 0 = lossless (huge files), ~18 = visually lossless, 23 = default,
# 28 = noticeably softer. 18-20 is a good "don't lose quality" target.
# Used when a conversion is triggered without a quality choice (e.g. the
# library-wide Settings > Tasks entries, which have no per-run UI).
CRF_VALUE = 18

# Named quality presets offered by the "Convert to H265" dialog in
# h265-ui.js (sent back as the `quality` arg) and by resolve_crf() below.
# Keep these keys in sync with the <select> options in h265-ui.js.
QUALITY_PRESETS = {
    "highest": 16,             # largest files, essentially lossless to the eye
    "visually_lossless": 18,   # recommended default — matches CRF_VALUE above
    "balanced": 20,            # smaller files, minimal visible difference
    "smaller": 23,             # x265's own default, noticeably more compression
    "smallest": 28,            # maximum compression, visibly softer
}

# x265 preset: slower presets squeeze more quality/size out of the same CRF.
# "slow" is a good quality/time tradeoff; use "medium" if conversions take
# too long on your hardware, or "veryslow" if you don't mind waiting.
X265_PRESET = "slow"

# Codec strings (as reported by ffprobe / Stash) that count as "already H265"
# and will be skipped.
ALREADY_DONE_CODECS = {"hevc", "h265", "x265"}

# Container/extension used for transcoded output.
OUTPUT_EXT = ".mp4"

# Name of the tag applied to scenes after a successful conversion, so a
# second run of this task won't re-encode them.
DONE_TAG_NAME = "H265 Converted"

# Path to the ffmpeg binary. "ffmpeg" assumes it's on PATH; change this if
# Stash's environment needs an explicit path (see Settings > System > ffmpeg).
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"


# Minimum length (seconds) a split segment must have to be kept. Guards
# against markers stacked within a fraction of a second of each other
# producing a near-empty clip.
MIN_SEGMENT_SECONDS = 0.5

# "fast" (default) stream-copies each segment — no quality loss, no
# re-encode time, but cuts snap to the nearest keyframe so a segment can
# start up to a couple of seconds before/after the exact marker time.
# "accurate" re-encodes each segment so cuts land exactly on the marker,
# at the cost of re-encode time (and a second, x264-based generation loss
# on top of whatever the source already was).
SPLIT_ACCURATE_DEFAULT = False

# Stash's id for this plugin — the yml manifest's filename minus ".yml".
# Must match PLUGIN_ID in h265-ui.js. Used to queue follow-up tasks.
PLUGIN_ID = "advancedFileOperations"

# Name of the tag applied to scenes after a successful repair.
REPAIR_TAG_NAME = "File Repaired"


# ---------------------------------------------------------------------------
# Stash plugin log protocol
# ---------------------------------------------------------------------------
# Stash reads plugin stderr line by line. A line that starts with an SOH
# (\x01) byte, then one of t/d/i/w/e/p, then an STX (\x02) byte, is parsed
# as a log line at that level and shown in the plugin log in the UI.
# Anything else (including a space instead of \x02) isn't recognised: it
# gets logged verbatim at Error level and progress lines don't move the
# task's progress bar. Progress lines use "p" and a value 0.0-1.0.

def _log(level, message):
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


# ---------------------------------------------------------------------------
# Stash GraphQL client
# ---------------------------------------------------------------------------

class StashClient:
    def __init__(self, server_connection):
        scheme = server_connection.get("Scheme", "http")
        host = server_connection.get("Host") or "localhost"
        if host in ("0.0.0.0", ""):
            host = "localhost"
        port = server_connection.get("Port", 9999)
        self.url = f"{scheme}://{host}:{port}/graphql"

        self.session = requests.Session()
        cookie = server_connection.get("SessionCookie")
        if cookie and cookie.get("Name") and cookie.get("Value"):
            self.session.cookies.set(cookie["Name"], cookie["Value"])
        api_key = server_connection.get("ApiKey") or os.environ.get("STASH_API_KEY")
        if api_key:
            self.session.headers["ApiKey"] = api_key

    def call(self, query, variables=None):
        resp = self.session.post(
            self.url, json={"query": query, "variables": variables or {}}, timeout=120
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"GraphQL error: {payload['errors']}")
        return payload["data"]

    # -- scenes -------------------------------------------------------

    def count_scenes(self):
        data = self.call(
            """
            query { findScenes(filter: { per_page: 0 }) { count } }
            """
        )
        return data["findScenes"]["count"]

    def find_scenes_page(self, page, per_page=50):
        data = self.call(
            """
            query($page: Int!, $per_page: Int!) {
              findScenes(filter: { page: $page, per_page: $per_page, sort: "id" }) {
                scenes {
                  id
                  title
                  tags { id name }
                  files {
                    id
                    path
                    video_codec
                  }
                }
              }
            }
            """,
            {"page": page, "per_page": per_page},
        )
        return data["findScenes"]["scenes"]

    def get_scene(self, scene_id):
        """
        Fetches a scene with everything the H265/split features need.
        Tries the modern field set first (multi-value `urls` + `stash_ids`);
        if this Stash version's schema doesn't have those, falls back to a
        query without them so the rest of the plugin still works — just
        without URL/StashDB copying during a split.
        """
        fields_modern = """
                id
                title
                details
                date
                urls
                stash_ids { endpoint stash_id }
                studio { id }
                performers { id }
                tags { id name }
                files { id path video_codec }
                scene_markers {
                  id
                  title
                  seconds
                  primary_tag { id name }
                  tags { id name }
                }
        """
        try:
            data = self.call(
                f"query($id: ID!) {{ findScene(id: $id) {{ {fields_modern} }} }}",
                {"id": scene_id},
            )
            return data["findScene"]
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Modern scene query failed ({exc}); retrying without urls/stash_ids")

        fields_fallback = """
                id
                title
                details
                date
                studio { id }
                performers { id }
                tags { id name }
                files { id path video_codec }
                scene_markers {
                  id
                  title
                  seconds
                  primary_tag { id name }
                  tags { id name }
                }
        """
        data = self.call(
            f"query($id: ID!) {{ findScene(id: $id) {{ {fields_fallback} }} }}",
            {"id": scene_id},
        )
        scene = data["findScene"]
        scene["urls"] = []
        scene["stash_ids"] = []
        return scene

    def find_scene_by_path(self, path):
        """
        Locates the scene Stash created for a given file path after a scan.
        Tries a direct path filter first; if that's not supported by this
        Stash version's schema, falls back to paging through the most
        recently created scenes and matching the file path client-side.
        """
        try:
            data = self.call(
                """
                query($path: String!) {
                  findScenes(
                    scene_filter: { path: { value: $path, modifier: EQUALS } }
                    filter: { per_page: 1 }
                  ) {
                    scenes { id }
                  }
                }
                """,
                {"path": path},
            )
            scenes = data["findScenes"]["scenes"]
            if scenes:
                return scenes[0]["id"]
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Path-filter scene lookup unavailable ({exc}); trying recent scenes instead")

        for page in range(1, 6):
            try:
                data = self.call(
                    """
                    query($page: Int!) {
                      findScenes(
                        filter: { page: $page, per_page: 50, sort: "created_at", direction: DESC }
                      ) {
                        scenes { id files { path } }
                      }
                    }
                    """,
                    {"page": page},
                )
            except Exception as exc:  # noqa: BLE001
                log_warn(f"Recent-scenes lookup failed: {exc}")
                return None
            scenes = data["findScenes"]["scenes"]
            if not scenes:
                break
            for scene in scenes:
                for f in scene.get("files") or []:
                    if f.get("path") == path:
                        return scene["id"]
        return None

    def update_scene_metadata(self, scene_id, title=None, details=None, date=None,
                               studio_id=None, performer_ids=None, tag_ids=None,
                               urls=None, stash_ids=None):
        scene_input = {"id": scene_id}
        if title is not None:
            scene_input["title"] = title
        if details is not None:
            scene_input["details"] = details
        if date is not None:
            scene_input["date"] = date
        if studio_id is not None:
            scene_input["studio_id"] = studio_id
        if performer_ids is not None:
            scene_input["performer_ids"] = performer_ids
        if tag_ids is not None:
            scene_input["tag_ids"] = tag_ids
        if urls:
            scene_input["urls"] = urls
        if stash_ids:
            scene_input["stash_ids"] = [
                {"endpoint": s["endpoint"], "stash_id": s["stash_id"]} for s in stash_ids
            ]

        try:
            self.call(
                """
                mutation($input: SceneUpdateInput!) {
                  sceneUpdate(input: $input) { id }
                }
                """,
                {"input": scene_input},
            )
        except Exception as exc:  # noqa: BLE001
            if "urls" in scene_input or "stash_ids" in scene_input:
                log_warn(f"sceneUpdate with urls/stash_ids failed ({exc}); retrying without them")
                scene_input.pop("urls", None)
                scene_input.pop("stash_ids", None)
                self.call(
                    """
                    mutation($input: SceneUpdateInput!) {
                      sceneUpdate(input: $input) { id }
                    }
                    """,
                    {"input": scene_input},
                )
            else:
                raise

    # -- multi-file scenes ------------------------------------------------
    # Used to fold a "keep original" conversion's new file back onto the
    # original scene (as its primary file) instead of leaving it stranded
    # in the separate, metadata-less scene Stash auto-creates for any file
    # it scans in that it doesn't already recognize.

    def assign_file_to_scene(self, scene_id, file_id):
        self.call(
            """
            mutation($scene_id: ID!, $file_id: ID!) {
              sceneAssignFile(input: { scene_id: $scene_id, file_id: $file_id })
            }
            """,
            {"scene_id": scene_id, "file_id": file_id},
        )

    def set_primary_file(self, scene_id, file_id):
        self.call(
            """
            mutation($id: ID!, $file_id: ID!) {
              sceneUpdate(input: { id: $id, primary_file_id: $file_id }) { id }
            }
            """,
            {"id": scene_id, "file_id": file_id},
        )

    def cleanup_empty_scene(self, scene_id):
        """
        Best-effort delete of the now-fileless placeholder scene left behind
        once its one file has been reassigned elsewhere. delete_file is
        always False here — by this point the file already belongs to the
        destination scene, so this only ever removes a DB row, never data.
        Not fatal if it fails (already gone, unsupported schema, etc.) — a
        stray empty scene is harmless clutter, not data loss.
        """
        try:
            self.call(
                """
                mutation($id: ID!) {
                  sceneDestroy(input: { id: $id, delete_file: false, delete_generated: true })
                }
                """,
                {"id": scene_id},
            )
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Couldn't clean up empty placeholder scene {scene_id}: {exc}")

    def create_marker(self, scene_id, seconds, title, primary_tag_id, tag_ids):
        data = self.call(
            """
            mutation($scene_id: ID!, $seconds: Float!, $title: String,
                     $primary_tag_id: ID!, $tag_ids: [ID!]) {
              sceneMarkerCreate(input: {
                scene_id: $scene_id, seconds: $seconds, title: $title,
                primary_tag_id: $primary_tag_id, tag_ids: $tag_ids
              }) { id }
            }
            """,
            {
                "scene_id": scene_id,
                "seconds": seconds,
                "title": title or "",
                "primary_tag_id": primary_tag_id,
                "tag_ids": tag_ids or [],
            },
        )
        return data["sceneMarkerCreate"]["id"]

    # -- tags -----------------------------------------------------------

    def find_or_create_tag(self, name):
        data = self.call(
            """
            query($name: String!) {
              findTags(tag_filter: { name: { value: $name, modifier: EQUALS } }) {
                tags { id name }
              }
            }
            """,
            {"name": name},
        )
        tags = data["findTags"]["tags"]
        if tags:
            return tags[0]["id"]

        data = self.call(
            """
            mutation($name: String!) {
              tagCreate(input: { name: $name }) { id }
            }
            """,
            {"name": name},
        )
        return data["tagCreate"]["id"]

    def add_tag_to_scene(self, scene_id, existing_tag_ids, new_tag_id):
        tag_ids = list(dict.fromkeys([*existing_tag_ids, new_tag_id]))
        self.call(
            """
            mutation($id: ID!, $tag_ids: [ID!]) {
              sceneUpdate(input: { id: $id, tag_ids: $tag_ids }) { id }
            }
            """,
            {"id": scene_id, "tag_ids": tag_ids},
        )

    # -- library ----------------------------------------------------------

    def run_plugin_task(self, description, args_map):
        """Queues another run of this plugin as a new Stash job. Tries the
        modern args_map form first (Stash v0.25+), falling back to the
        older PluginArgInput list form — same as runTask() in h265-ui.js."""
        try:
            self.call(
                """
                mutation($plugin_id: ID!, $description: String, $args_map: Map) {
                  runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map)
                }
                """,
                {"plugin_id": PLUGIN_ID, "description": description, "args_map": args_map},
            )
        except Exception:  # noqa: BLE001
            args = [{"key": k, "value": {"str": str(v)}} for k, v in args_map.items()]
            self.call(
                """
                mutation($plugin_id: ID!, $description: String, $args: [PluginArgInput!]) {
                  runPluginTask(plugin_id: $plugin_id, description: $description, args: $args)
                }
                """,
                {"plugin_id": PLUGIN_ID, "description": description, "args": args},
            )

    def scan_generate_options(self):
        """
        What a scan started by this plugin should generate. A metadataScan
        call with only `paths` generates nothing — no cover, no phash — so
        this starts from the "Scan" defaults saved under Settings > Tasks
        (whatever the person normally scans with), then always switches on
        covers and phashes on top, since a new scene without either is
        barely usable. If this Stash version can't report those defaults,
        it's just covers and phashes.
        """
        options = {}
        try:
            data = self.call(
                """
                query {
                  configuration {
                    defaults {
                      scan {
                        scanGenerateCovers
                        scanGeneratePreviews
                        scanGenerateImagePreviews
                        scanGenerateSprites
                        scanGeneratePhashes
                        scanGenerateThumbnails
                        scanGenerateClipPreviews
                      }
                    }
                  }
                }
                """
            )
            defaults = ((data.get("configuration") or {}).get("defaults") or {}).get("scan") or {}
            options = {k: True for k, v in defaults.items() if v is True}
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Couldn't read your default scan settings ({exc}); generating covers and phashes only")
        options["scanGenerateCovers"] = True
        options["scanGeneratePhashes"] = True
        return options

    def rescan_paths(self, paths):
        """Triggers a scan and returns whatever metadataScan resolves to —
        a job id string on Stash versions with a job queue, or a plain
        boolean on older ones."""
        scan_input = {"paths": paths, **self.scan_generate_options()}
        try:
            data = self.call(
                """
                mutation($input: ScanMetadataInput!) {
                  metadataScan(input: $input)
                }
                """,
                {"input": scan_input},
            )
        except Exception as exc:  # noqa: BLE001
            # A generate option this Stash version doesn't know rejects the
            # whole scan, so fall back to one that at least picks the files up.
            log_warn(f"Scan with generate options failed ({exc}); scanning without them")
            data = self.call(
                """
                mutation($paths: [String!]) {
                  metadataScan(input: { paths: $paths })
                }
                """,
                {"paths": paths},
            )
        return data.get("metadataScan")


# ---------------------------------------------------------------------------
# Transcoding
# ---------------------------------------------------------------------------

def needs_conversion(video_file):
    codec = (video_file.get("video_codec") or "").lower()
    return codec not in ALREADY_DONE_CODECS


def probe_ok(path):
    """Quick ffprobe sanity check that a file has a readable video stream."""
    try:
        result = subprocess.run(
            [
                FFPROBE_BIN, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True, text=True, timeout=60,
        )
        return bool(result.stdout.strip())
    except Exception as exc:  # noqa: BLE001
        log_warn(f"ffprobe check failed for {path}: {exc}")
        return False


# Audio codecs every major browser can play from an .mp4. Anything else
# (AC3, DTS, PCM, FLAC, ...) is re-encoded to AAC during conversion, since
# copying it as-is leaves a file that plays silent or not at all in a
# browser.
BROWSER_AUDIO_CODECS = {"aac", "mp3"}


def probe_audio_codecs(path):
    """Codec names of every audio stream in `path`, e.g. ["aac", "ac3"].
    Empty if there's no audio, or ffprobe couldn't tell."""
    try:
        result = subprocess.run(
            [
                FFPROBE_BIN, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True, text=True, timeout=60,
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except Exception as exc:  # noqa: BLE001
        log_warn(f"Couldn't read audio codecs of {path}, re-encoding audio to be safe: {exc}")
        return ["unknown"]


_FFMPEG_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _is_ffmpeg_stats_line(line):
    """
    True if this looks like one of ffmpeg's own periodic progress lines
    (`frame=... time=... bitrate=... speed=...`) rather than an actual
    error/warning. Used to filter those back out where a caller (namely
    detect_corruption) needs to tell real stderr content apart from the
    stats output it had to turn on just to get progress out of `-v error`.
    """
    return "speed=" in line and "bitrate=" in line and "time=" in line


def run_ffmpeg_tracking_progress(cmd, duration=None, on_progress=None, timeout=None):
    """
    Runs an ffmpeg command, streaming its stderr line by line instead of
    blocking on subprocess.run() until it exits. If `duration` (seconds)
    and `on_progress` (a callable taking a 0.0-1.0 fraction) are given,
    parses each "...time=01:23:45.67..." status line ffmpeg prints as it
    works and reports how far through the source that timestamp is — this
    is what lets a long single-file operation actually move the task's
    progress bar instead of sitting frozen until the whole thing finishes.

    `timeout`, if given, kills the process and raises
    subprocess.TimeoutExpired once that many seconds of wall-clock time
    have passed — matching subprocess.run(timeout=...)'s behavior so
    existing callers don't need to change their handling.

    Returns (returncode, stderr_text) — stderr_text is ffmpeg's full
    stderr, same as subprocess.run(capture_output=True) would have given,
    for existing error-message handling to keep using unchanged.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    stderr_lines = []
    last_reported = -1.0
    start_time = time.monotonic()
    timed_out = False
    try:
        for line in proc.stderr:
            stderr_lines.append(line)
            if timeout is not None and (time.monotonic() - start_time) > timeout:
                timed_out = True
                proc.kill()
                break
            if not (duration and on_progress):
                continue
            match = _FFMPEG_TIME_RE.search(line)
            if not match:
                continue
            h, m, s = match.groups()
            elapsed = int(h) * 3600 + int(m) * 60 + float(s)
            fraction = max(0.0, min(1.0, elapsed / duration))
            # Throttle: ffmpeg prints a status line multiple times a
            # second, and log_progress writes a line every call — only
            # report on a real (>=1%) change so the plugin log doesn't
            # fill up with near-duplicate progress lines.
            if fraction - last_reported >= 0.01 or fraction >= 1.0:
                on_progress(fraction)
                last_reported = fraction
    finally:
        proc.wait()
    if timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout, output=None, stderr="".join(stderr_lines))
    return proc.returncode, "".join(stderr_lines)


def resolve_crf(args):
    """
    Resolves the CRF to encode at from plugin args. A named quality preset
    (`quality`, one of QUALITY_PRESETS) takes precedence; a raw numeric
    override (`crf`, 0-51) is used if there's no preset; otherwise falls
    back to CRF_VALUE. An invalid value logs a warning and falls back
    rather than failing the whole run.
    """
    quality = (args.get("quality") or "").strip().lower()
    if quality:
        if quality in QUALITY_PRESETS:
            return QUALITY_PRESETS[quality]
        log_warn(f"Unknown quality preset '{quality}', falling back to default CRF {CRF_VALUE}")
        return CRF_VALUE

    crf_arg = args.get("crf")
    if crf_arg not in (None, ""):
        try:
            crf_value = int(crf_arg)
            if 0 <= crf_value <= 51:
                return crf_value
            log_warn(f"crf value {crf_value} out of range (0-51), falling back to default CRF {CRF_VALUE}")
        except (TypeError, ValueError):
            log_warn(f"Invalid crf value '{crf_arg}', falling back to default CRF {CRF_VALUE}")

    return CRF_VALUE


def transcode_to_h265(src_path, crf=None, on_progress=None):
    """
    Encodes src_path to H.265 in a temp file, then returns that temp path.
    Raises on failure. Caller is responsible for moving/cleaning up.
    `crf` overrides CRF_VALUE for this encode (see resolve_crf()).
    `on_progress`, if given, is called with a 0.0-1.0 fraction as ffmpeg
    works through the source, based on the source's known duration —
    without this the task's progress bar would otherwise sit frozen for
    the entire length of the encode.
    """
    if not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)

    crf_value = CRF_VALUE if crf is None else crf

    try:
        duration = get_duration_seconds(src_path)
    except Exception as exc:  # noqa: BLE001
        log_warn(f"Couldn't read source duration, progress won't be reported for this file: {exc}")
        duration = None

    tmp_dir = tempfile.gettempdir()
    fd, tmp_path = tempfile.mkstemp(suffix=OUTPUT_EXT, dir=tmp_dir)
    os.close(fd)

    audio_codecs = probe_audio_codecs(src_path)
    if all(c in BROWSER_AUDIO_CODECS for c in audio_codecs):
        audio_args = ["-c:a", "copy"]
    else:
        log_info(f"Audio is {', '.join(audio_codecs)}, which browsers can't play from an .mp4 — re-encoding it to AAC")
        audio_args = ["-c:a", "aac", "-b:a", "192k"]

    # Everything below is chosen for the result to stream well in a browser:
    #   - hvc1 tag: without it Safari/Apple players refuse H.265 in .mp4.
    #   - yuv420p: 8-bit 4:2:0, the only H.265 flavour browsers that play
    #     H.265 at all reliably decode in hardware.
    #   - open-gop=0: every keyframe is a clean restart point, so seeking
    #     lands on the exact spot instead of glitching or failing.
    #   - +faststart: puts the index (moov atom) at the start of the file.
    #     ffmpeg's default is the end, which makes a browser fetch the end
    #     of the file before it can start playing or seek.
    video_args = [
        "-c:v", "libx265",
        "-preset", X265_PRESET,
        "-crf", str(crf_value),
        "-x265-params", "open-gop=0",
        "-tag:v", "hvc1",
        "-pix_fmt", "yuv420p",
    ]
    container_args = ["-movflags", "+faststart"]

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", src_path,
        "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
        *video_args,
        *audio_args,
        "-c:s", "copy",
        *container_args,
        tmp_path,
    ]

    log_info(f"Transcoding at CRF {crf_value}: {src_path}")
    returncode, stderr = run_ffmpeg_tracking_progress(cmd, duration=duration, on_progress=on_progress)
    if returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
        # Common fallback: source has a subtitle stream ffmpeg can't copy
        # into mp4 (e.g. PGS). Retry once without subtitles.
        log_warn("First encode attempt failed, retrying without subtitle copy...")
        cmd_no_subs = [
            FFMPEG_BIN, "-y", "-i", src_path,
            "-map", "0:v:0", "-map", "0:a?",
            *video_args,
            *audio_args,
            *container_args,
            tmp_path,
        ]
        returncode, stderr = run_ffmpeg_tracking_progress(cmd_no_subs, duration=duration, on_progress=on_progress)
        if returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
            raise RuntimeError(f"ffmpeg failed on {src_path}: {stderr[-2000:]}")

    if not probe_ok(tmp_path):
        os.remove(tmp_path)
        raise RuntimeError(f"Output file failed ffprobe sanity check: {src_path}")

    return tmp_path


def finalize_output(src_path, tmp_path, keep_original):
    """
    Moves the transcoded temp file into place next to the source.
    Returns (final_path, old_path_removed_or_None) for rescanning/cleanup.
    """
    base, _ext = os.path.splitext(src_path)

    if keep_original:
        final_path = f"{base}.h265{OUTPUT_EXT}"
        shutil.move(tmp_path, final_path)
        return final_path, None

    final_path = f"{base}{OUTPUT_EXT}"
    same_container = os.path.abspath(final_path) == os.path.abspath(src_path)

    if same_container:
        # Overwrite in place via a rename swap so we never leave a corrupt file.
        shutil.move(tmp_path, final_path)
    else:
        shutil.move(tmp_path, final_path)
        os.remove(src_path)

    return final_path, src_path


def link_converted_file_to_scene(client, scene, new_path):
    """
    After a "keep original" conversion, the new H265 file at new_path was
    just scanned in as its own auto-created scene — Stash makes a fresh
    scene for any file it scans that it doesn't already recognize, since a
    re-encode has a different hash than the source. This finds that
    placeholder scene, reassigns its file onto the *original* scene (so it
    keeps its title/tags/markers/O-counter/etc.), sets that file as the
    original scene's primary file, and cleans up the now-empty placeholder.

    Returns True if the file ended up attached as the primary file, False
    if anything went wrong — in which case the converted file is still
    safely on disk and already scanned in (just as its own bare scene), so
    nothing is lost; it only needs a manual "Set as primary" in Stash.
    """
    new_scene_id = client.find_scene_by_path(new_path)
    if not new_scene_id:
        log_warn(f"Converted file was scanned in, but couldn't find its placeholder scene to link it: {new_path}")
        return False

    try:
        new_scene = client.get_scene(new_scene_id)
        new_files = new_scene.get("files") or []
        new_file_id = new_files[0]["id"] if new_files else None
        if not new_file_id:
            log_warn(f"Placeholder scene {new_scene_id} has no file id to link")
            return False

        client.assign_file_to_scene(scene["id"], new_file_id)
        client.set_primary_file(scene["id"], new_file_id)
        client.cleanup_empty_scene(new_scene_id)
        return True
    except Exception as exc:  # noqa: BLE001
        log_warn(
            f"Converted file is on disk and scanned in (as scene {new_scene_id}), but couldn't "
            f"automatically attach it to scene {scene['id']} as the primary file ({exc}). "
            f"Attach it yourself in Stash: open scene {scene['id']}'s editor, Files tab, "
            f"add the file from scene {new_scene_id}, and set it as primary."
        )
        return False


def scene_name(scene):
    """How a scene is named in task names: its title, or its file name when
    it never got one (Stash leaves the title empty then). Same rule as
    sceneLabel() in h265-ui.js."""
    files = scene.get("files") or []
    name = scene.get("title") or (os.path.basename(files[0]["path"]) if files else "")
    return f'"{name}"' if name else f"scene {scene['id']}"


def scene_label(scene):
    """How a scene is named in log lines: scene_name() plus its id, so two
    scenes with the same title can still be told apart."""
    name = scene_name(scene)
    return name if name.startswith("scene ") else f"{name} (scene {scene['id']})"


def process_scene(client, scene, keep_original, done_tag_id, followups, crf=None, on_progress=None):
    """
    Converts one scene's primary video file to H265 if it needs it.
    Returns a short status string: "converted" / "skipped" / "failed: <why>".
    Raises nothing — failures are reported in the return value so a batch
    run can keep going. `crf` overrides CRF_VALUE (see resolve_crf()).
    `on_progress`, if given, is forwarded to transcode_to_h265 (see there).

    keep_original never deletes the source file. When set, the new H265
    file is written alongside it, attached to this same scene, and made
    the scene's primary file (so playback/thumbnails switch to it) — the
    original stays right where it was, just as a secondary file on the
    scene rather than the primary one.

    Nothing here scans or attaches the new file: Stash runs one job at a
    time, so a scan can't start while this task runs. Instead, what needs
    doing afterwards is appended to `followups` for
    queue_convert_followups() to queue once the caller is done.
    """
    tag_names = {t["name"] for t in scene.get("tags", [])}
    if done_tag_id and tag_names and DONE_TAG_NAME in tag_names:
        return "skipped"

    files = scene.get("files") or []
    if not files:
        return "skipped"

    video_file = files[0]
    if not needs_conversion(video_file):
        return "skipped"

    src_path = video_file["path"]
    log_info(f"Converting {scene_label(scene)} to H265...")
    try:
        tmp_path = transcode_to_h265(src_path, crf=crf, on_progress=on_progress)
        final_path, removed_path = finalize_output(src_path, tmp_path, keep_original)

        existing_tag_ids = [t["id"] for t in scene.get("tags", [])]
        client.add_tag_to_scene(scene["id"], existing_tag_ids, done_tag_id)

        rescan_paths = [final_path]
        if removed_path and removed_path != final_path:
            rescan_paths.append(os.path.dirname(removed_path))

        # The new file needs attaching to this scene whenever it's at a new
        # path — always with keep_original, and when replacing a non-.mp4
        # source. Stash sees such a file as brand new and gives it its own
        # bare scene. Overwriting a .mp4 in place keeps the path, so Stash
        # just updates the existing file on this same scene.
        needs_link = os.path.abspath(final_path) != os.path.abspath(src_path)
        followups.append({
            "scene_id": str(scene["id"]),
            "new_path": final_path,
            "scan_paths": rescan_paths,
            "link": needs_link,
        })

        note = " — the new file gets attached to this scene after the scan" if needs_link else ""
        log_info(f"Converted {scene_label(scene)}{note}")
        return "converted"
    except Exception as exc:  # noqa: BLE001
        log_error(f"Failed on {scene_label(scene)} ({src_path}): {exc}")
        return f"failed: {exc}"


def queue_convert_followups(client, followups, description):
    """
    Queues what process_scene() left to do: one scan of every new file,
    then — if any of them need attaching to their scene — one
    "convert_finalize" task behind it. Stash runs its queue in order, so
    the new files' scenes exist by the time that task starts.
    """
    if not followups:
        return
    scan_paths = []
    for f in followups:
        scan_paths.extend(p for p in f["scan_paths"] if p not in scan_paths)
    client.rescan_paths(scan_paths)

    links = [[f["scene_id"], f["new_path"]] for f in followups if f["link"]]
    if not links:
        return
    try:
        client.run_plugin_task(description, {"mode": "convert_finalize", "links": json.dumps(links)})
        log_info(f"Queued a scan, then \"{description}\" to attach {len(links)} new file(s) to their scenes.")
    except Exception as exc:  # noqa: BLE001
        log_error(
            f"Couldn't queue the task that attaches the converted file(s) to their scenes ({exc}). "
            f"After the scan, each will show up as its own scene — attach it by hand in the original "
            f"scene's editor (Files tab) and set it as primary: "
            + ", ".join(os.path.basename(p) for _, p in links)
        )


def run_convert_finalize(client, args):
    """
    Second half of a conversion, queued by queue_convert_followups() behind
    the scan of the new files: attaches each new file to its original
    scene as the primary file and removes the bare scene Stash made for it.
    """
    try:
        links = json.loads(args.get("links") or "[]")
    except ValueError as exc:
        write_plugin_output(error=f"convert_finalize got an invalid links argument: {exc}")
        return

    attached = 0
    for idx, (scene_id, new_path) in enumerate(links, start=1):
        log_progress((idx - 1) / max(len(links), 1))
        scene = client.get_scene(scene_id)
        if not scene:
            log_warn(f"Scene {scene_id} no longer exists; {os.path.basename(new_path)} stays its own scene")
            continue
        if link_converted_file_to_scene(client, scene, new_path):
            attached += 1
            log_info(f"Attached {os.path.basename(new_path)} to {scene_label(scene)} as its primary file")

    log_progress(1.0)
    summary = f"Attached {attached} of {len(links)} converted file(s) to their scenes."
    if attached < len(links):
        summary += " See the warnings above for the rest."
    log_info(summary)
    write_plugin_output(output=summary)


# ---------------------------------------------------------------------------
# Splitting a scene at its markers
# ---------------------------------------------------------------------------

def get_duration_seconds(path):
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60,
    )
    return float(result.stdout.strip())


def cut_segment(src_path, start, end, out_path, accurate, on_progress=None):
    duration = end - start
    if accurate:
        # Re-encodes so the cut lands exactly on the marker, at the cost of
        # time and a second generation of lossy compression. Slow enough on
        # a long segment that it's worth reporting progress for.
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", src_path, "-ss", str(start), "-t", str(duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            out_path,
        ]
        returncode, stderr = run_ffmpeg_tracking_progress(cmd, duration=duration, on_progress=on_progress)
    else:
        # Stream-copy: no re-encode, no quality loss, but the cut snaps to
        # the nearest keyframe so it can land a little before/after the
        # exact marker time. Bounded by disk I/O rather than decode speed,
        # but on a large file on a slow or network disk that can still be
        # minutes per part, so progress is tracked here too.
        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", str(start), "-i", src_path, "-t", str(duration),
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            out_path,
        ]
        returncode, stderr = run_ffmpeg_tracking_progress(cmd, duration=duration, on_progress=on_progress)

    if returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"ffmpeg failed cutting [{start:.2f}s, {end:.2f}s): {stderr[-1500:]}")


def run_split_scene(client, args):
    scene_id = args.get("scene_id")
    if not scene_id:
        write_plugin_output(error="split_scene mode requires a scene_id argument")
        return

    keep_original = str(args.get("keep_original", "true")).lower() == "true"
    accurate = str(args.get("accurate", str(SPLIT_ACCURATE_DEFAULT))).lower() == "true"

    scene = client.get_scene(scene_id)
    if not scene:
        write_plugin_output(error=f"No scene found with id {scene_id}")
        return

    files = scene.get("files") or []
    if not files:
        write_plugin_output(error="Scene has no file to split")
        return
    src_path = files[0]["path"]

    markers = scene.get("scene_markers") or []

    try:
        duration = get_duration_seconds(src_path)
    except Exception as exc:  # noqa: BLE001
        write_plugin_output(error=f"Could not read duration of source file: {exc}")
        return

    # cut_seconds, when given, is a comma-separated list of exact timestamps
    # the caller picked (e.g. from the "which markers to cut at" dialog in
    # h265-ui.js). Falls back to "cut at every marker" when omitted, so the
    # mode still works if triggered without that dialog (e.g. by hand from
    # Settings > Tasks with an explicit scene_id).
    #
    # ranges, when given, takes precedence: a comma-separated list of
    # "start-end" pairs (the dialog's "each marker as its own clip" mode),
    # each cut out as its own part. An empty end means "to the end of the
    # file". Unlike cut points, these don't have to cover the whole video,
    # and one range alone is a valid split.
    ranges_arg = (args.get("ranges") or "").strip()
    cut_seconds_arg = (args.get("cut_seconds") or "").strip()
    segments = []
    if ranges_arg:
        try:
            for item in ranges_arg.split(","):
                if not item.strip():
                    continue
                start_s, _, end_s = item.strip().partition("-")
                start = max(0.0, round(float(start_s), 3))
                end = min(duration, round(float(end_s), 3)) if end_s.strip() else duration
                if end - start >= MIN_SEGMENT_SECONDS:
                    segments.append((start, end))
        except ValueError as exc:
            write_plugin_output(error=f"Invalid ranges value: {exc}")
            return
        segments = sorted(set(segments))
        if not segments:
            write_plugin_output(error="None of the chosen marker ranges is long enough to cut")
            return
        split_desc = f"from {len(segments)} marker range(s)"
    else:
        if cut_seconds_arg:
            try:
                cut_points = sorted({round(float(s), 3) for s in cut_seconds_arg.split(",") if s.strip()})
            except ValueError as exc:
                write_plugin_output(error=f"Invalid cut_seconds value: {exc}")
                return
        else:
            cut_points = sorted({round(float(m["seconds"]), 3) for m in markers if float(m["seconds"]) > 0})

        cut_points = [c for c in cut_points if 0 < c < duration]
        if not cut_points:
            write_plugin_output(error="No valid cut points to split at (need at least one marker strictly between 0:00 and the end)")
            return

        boundaries = [0.0] + cut_points + [duration]
        for i in range(len(boundaries) - 1):
            start, end = boundaries[i], boundaries[i + 1]
            if end - start >= MIN_SEGMENT_SECONDS:
                segments.append((start, end))

        if len(segments) < 2:
            write_plugin_output(error="Markers didn't produce more than one usable segment; nothing to split")
            return
        split_desc = f"at {len(cut_points)} marker(s)"

    base_dir = os.path.dirname(src_path)
    base_name, ext = os.path.splitext(os.path.basename(src_path))
    log_info(f"Splitting {scene_label(scene)} into {len(segments)} part(s) {split_desc}...")

    # Cutting is where nearly all the time goes, so it gets the progress
    # bar; within it each part's share is proportional to its length,
    # since that's what ffmpeg's time is spent on — a 20-minute part
    # shouldn't move the bar as much as a 20-second one.
    CUT_END = 0.95
    total_length = sum(end - start for start, end in segments) or 1.0

    out_paths = []
    out_path = None
    try:
        done_length = 0.0
        for idx, (start, end) in enumerate(segments, start=1):
            base = done_length / total_length * CUT_END
            slice_size = (end - start) / total_length * CUT_END
            log_progress(base)
            log_info(f"Cutting part {idx}/{len(segments)} ({end - start:.0f}s)...")

            def on_progress(fraction, base=base, slice_size=slice_size):
                log_progress(base + fraction * slice_size)

            out_path = os.path.join(base_dir, f"{base_name}.p{idx}{ext}")
            cut_segment(src_path, start, end, out_path, accurate, on_progress=on_progress)
            out_paths.append((out_path, start, end))
            done_length += end - start
    except Exception as exc:  # noqa: BLE001
        # Includes the part that was being written when it failed, which
        # isn't in out_paths yet.
        for p in [p for p, _, _ in out_paths] + [out_path]:
            if p and os.path.isfile(p):
                os.remove(p)
        write_plugin_output(error=f"Splitting failed, no changes made: {exc}")
        return
    log_progress(CUT_END)

    # Stash runs one job at a time, and this task is itself a job — so a
    # scan started from here can't run until this task has ended, and
    # waiting for it would just hang. Instead, queue the scan and then a
    # follow-up "split_finalize" task behind it: the queue runs them in
    # order, so by the time the follow-up starts the new scenes exist.
    log_info("Queueing a scan of the new files, then a follow-up task to copy the scene details onto them...")
    client.rescan_paths([p for p, _, _ in out_paths])

    try:
        client.run_plugin_task(
            f"Finish splitting {scene_name(scene)}",
            {
                "mode": "split_finalize",
                "scene_id": str(scene_id),
                "keep_original": "true" if keep_original else "false",
                "duration": str(duration),
                "parts": json.dumps([[p, s, e] for p, s, e in out_paths]),
            },
        )
    except Exception as exc:  # noqa: BLE001
        log_progress(1.0)
        write_plugin_output(
            error=(
                f"Cut {len(out_paths)} part(s) and queued a scan, but couldn't queue the follow-up task "
                f"that copies title/performers/tags/markers onto them ({exc}). The files are on disk "
                f"next to the original; their scenes will need those details added by hand."
            )
        )
        return

    log_progress(1.0)
    summary = (
        f"Cut {scene_label(scene)} into {len(out_paths)} part(s). Scene details are copied "
        f'onto them by the "Finish splitting" task, which runs right after the scan.'
    )
    log_info(summary)
    write_plugin_output(output=summary)


def run_split_finalize(client, args):
    """
    Second half of a split, queued by run_split_scene behind the scan of
    the new files: finds each part's new scene and copies the original
    scene's details and the markers that fall inside that part onto it.
    """
    scene_id = args.get("scene_id")
    try:
        parts = json.loads(args.get("parts") or "[]")
        duration = float(args.get("duration"))
    except (TypeError, ValueError) as exc:
        write_plugin_output(error=f"split_finalize got invalid parts/duration arguments: {exc}")
        return
    keep_original = str(args.get("keep_original", "true")).lower() == "true"

    scene = client.get_scene(scene_id) if scene_id else None
    if not scene or not parts:
        write_plugin_output(error=f"split_finalize: no original scene {scene_id} or no parts to finish")
        return

    markers = scene.get("scene_markers") or []
    files = scene.get("files") or []
    src_path = files[0]["path"] if files else None
    base_name = os.path.splitext(os.path.basename(src_path))[0] if src_path else f"scene {scene_id}"

    performer_ids = [p["id"] for p in scene.get("performers") or []]
    tag_ids = [t["id"] for t in scene.get("tags") or []]
    studio_id = scene["studio"]["id"] if scene.get("studio") else None
    original_title = scene.get("title") or base_name

    created, needs_follow_up = 0, 0
    for idx, (out_path, start, end) in enumerate(parts, start=1):
        log_progress((idx - 1) / len(parts))
        start, end = float(start), float(end)

        new_scene_id = client.find_scene_by_path(out_path)
        if not new_scene_id:
            log_error(
                f"Split '{os.path.basename(out_path)}' but couldn't find the scene Stash "
                f"created for it — trigger a manual Scan and re-check it in if it's missing."
            )
            needs_follow_up += 1
            continue

        try:
            client.update_scene_metadata(
                new_scene_id,
                title=f"{original_title} #{idx}",
                details=scene.get("details"),
                date=scene.get("date"),
                studio_id=studio_id,
                performer_ids=performer_ids,
                tag_ids=tag_ids,
                urls=scene.get("urls"),
                stash_ids=scene.get("stash_ids"),
            )
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Copied file but couldn't copy metadata to new scene {new_scene_id}: {exc}")

        # A marker sitting exactly on the file's very end has no later part
        # to go into, so it belongs to whichever part ends there.
        segment_markers = [
            m for m in markers
            if start <= float(m["seconds"]) < end
            or (end >= duration and float(m["seconds"]) == end)
        ]
        marker_count = 0
        for m in segment_markers:
            primary_tag = m.get("primary_tag") or {}
            primary_tag_id = primary_tag.get("id")
            if not primary_tag_id:
                continue
            new_seconds = max(0.0, round(float(m["seconds"]) - start, 3))
            marker_tag_ids = [t["id"] for t in m.get("tags") or []]
            try:
                client.create_marker(new_scene_id, new_seconds, m.get("title"), primary_tag_id, marker_tag_ids)
                marker_count += 1
            except Exception as exc:  # noqa: BLE001
                log_warn(f"Failed to recreate marker '{m.get('title')}' on new scene {new_scene_id}: {exc}")

        created += 1
        log_info(
            f'Part {idx}: "{original_title} #{idx}" (scene {new_scene_id}, {os.path.basename(out_path)}), '
            f"{marker_count} marker(s) carried over"
        )

    if not keep_original and src_path:
        try:
            os.remove(src_path)
            # Queued, not waited on — same one-job-at-a-time reason as above.
            client.rescan_paths([os.path.dirname(src_path)])
            log_info(f"Removed original file: {src_path}")
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Split succeeded but couldn't remove the original file: {exc}")

    log_progress(1.0)
    summary = (
        f"Split {scene_label(scene)} into {len(parts)} part(s): "
        f"{created} fully set up, {needs_follow_up} need a manual look."
    )
    log_info(summary)
    write_plugin_output(output=summary)


# ---------------------------------------------------------------------------
# Repairing a corrupt file
# ---------------------------------------------------------------------------

def make_temp_output(ext=OUTPUT_EXT):
    fd, tmp_path = tempfile.mkstemp(suffix=ext, dir=tempfile.gettempdir())
    os.close(fd)
    return tmp_path


def detect_corruption(path, timeout=1800, on_progress=None):
    """
    Decodes the whole file (video, audio, everything) through ffmpeg,
    throwing the output away, and watches for decode errors. This is the
    same technique "verify my rip" scripts use — it's slower than just
    opening the file (which only reads the container), but it's the only
    reliable way to catch mid-file corruption rather than just a broken
    header. Returns (is_corrupt, detail_message).

    `on_progress`, if given, is called with a 0.0-1.0 fraction as the
    check proceeds — this step alone can take as long as the file's full
    runtime, so without it the task's progress bar would sit frozen for
    the entire check. `-stats` is added explicitly to get those periodic
    "time=..." lines out of ffmpeg despite `-v error` (which suppresses
    them by default); they're filtered back out of the real stderr text
    below so a healthy file still reports a clean, error-free result.
    """
    try:
        duration = get_duration_seconds(path)
    except Exception as exc:  # noqa: BLE001
        log_warn(f"Couldn't read duration for corruption-check progress: {exc}")
        duration = None

    cmd = [FFMPEG_BIN, "-v", "error", "-stats", "-xerror", "-i", path, "-map", "0", "-f", "null", "-"]
    try:
        returncode, stderr = run_ffmpeg_tracking_progress(cmd, duration=duration, on_progress=on_progress, timeout=timeout)
    except subprocess.TimeoutExpired:
        return True, "Corruption check timed out (very large or very slow file) — treating it as needing repair"

    real_stderr = "\n".join(
        line for line in stderr.splitlines() if line.strip() and not _is_ffmpeg_stats_line(line)
    ).strip()
    if returncode != 0 or real_stderr:
        return True, (real_stderr or f"ffmpeg exited with code {returncode}")
    return False, ""


def remux_repair(src_path, on_progress=None):
    """
    Attempts a lossless container remux: copies every stream as-is into a
    fresh, cleanly-indexed file. This alone fixes most "won't seek", "wrong
    duration", "moov atom not found" style container corruption without
    touching a single pixel of the actual video. Returns the temp output
    path on success, or None if the remux didn't produce a clean file
    (meaning the damage is in the stream data itself, not just the
    container, and a re-encode repair is needed instead).
    """
    tmp_path = make_temp_output()
    try:
        duration = get_duration_seconds(src_path)
    except Exception:  # noqa: BLE001
        duration = None

    cmd = [
        FFMPEG_BIN, "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        "-i", src_path,
        "-map", "0",
        "-c", "copy",
        "-movflags", "faststart",
        tmp_path,
    ]
    returncode, _stderr = run_ffmpeg_tracking_progress(cmd, duration=duration, on_progress=on_progress)
    ok = (
        returncode == 0
        and os.path.isfile(tmp_path)
        and os.path.getsize(tmp_path) > 0
        and probe_ok(tmp_path)
    )
    if not ok:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        return None
    return tmp_path


def reencode_repair(src_path, on_progress=None):
    """
    Last-resort repair: fully re-decodes and re-encodes, telling ffmpeg to
    ignore and skip corrupt packets rather than aborting. This recovers as
    much of the file as is decodable, but is lossy (re-compresses on top of
    whatever the source already was) and any genuinely unreadable stretch
    of the file will come out as a skip or a brief glitch rather than being
    magically restored — there's no way to reconstruct video data that's
    actually gone.
    """
    tmp_path = make_temp_output()
    try:
        duration = get_duration_seconds(src_path)
    except Exception:  # noqa: BLE001
        duration = None

    cmd = [
        FFMPEG_BIN, "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+discardcorrupt",
        "-i", src_path,
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        tmp_path,
    ]
    returncode, stderr = run_ffmpeg_tracking_progress(cmd, duration=duration, on_progress=on_progress)
    ok = (
        returncode == 0
        and os.path.isfile(tmp_path)
        and os.path.getsize(tmp_path) > 0
        and probe_ok(tmp_path)
    )
    if not ok:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError(f"Re-encode repair failed: {stderr[-1500:]}")
    return tmp_path


def finalize_repaired_output(src_path, tmp_path, keep_original):
    """Same idea as finalize_output(), but with a distinct suffix so a
    repaired file is never confused with an H265-converted one."""
    base, _ext = os.path.splitext(src_path)

    if keep_original:
        final_path = f"{base}.repaired{OUTPUT_EXT}"
        shutil.move(tmp_path, final_path)
        return final_path, None

    final_path = f"{base}{OUTPUT_EXT}"
    same_container = os.path.abspath(final_path) == os.path.abspath(src_path)
    if same_container:
        shutil.move(tmp_path, final_path)
    else:
        shutil.move(tmp_path, final_path)
        os.remove(src_path)
    return final_path, src_path


def run_repair_scene(client, args, repair_tag_id):
    scene_id = args.get("scene_id")
    if not scene_id:
        write_plugin_output(error="repair_scene mode requires a scene_id argument")
        return

    force = str(args.get("force", "false")).lower() == "true"
    keep_original = str(args.get("keep_original", "true")).lower() == "true"

    scene = client.get_scene(scene_id)
    if not scene:
        write_plugin_output(error=f"No scene found with id {scene_id}")
        return

    files = scene.get("files") or []
    if not files:
        write_plugin_output(error="Scene has no file to repair")
        return
    src_path = files[0]["path"]

    log_info(
        f"Checking {scene_label(scene)} ({os.path.basename(src_path)}) for corruption "
        f"(this decodes the whole file, so it can take a while)..."
    )
    log_progress(0.05)

    def on_check_progress(fraction):
        log_progress(0.05 + fraction * 0.45)

    is_corrupt, detail = detect_corruption(src_path, on_progress=on_check_progress)

    if not is_corrupt and not force:
        write_plugin_output(output=f"{scene_label(scene)}: no corruption detected — the file decodes cleanly, nothing to repair.")
        return
    if is_corrupt:
        log_warn(f"Corruption detected: {detail[:800]}")
    else:
        log_info("No corruption detected, but repairing anyway since force was requested.")
    log_progress(0.5)

    log_info("Attempting a lossless remux repair first...")

    def on_remux_progress(fraction):
        log_progress(0.5 + fraction * 0.05)

    tmp_path = remux_repair(src_path, on_progress=on_remux_progress)
    method = "lossless remux"

    if tmp_path is None:
        log_warn(
            "Remux alone didn't produce a clean file, so the damage is in the stream "
            "data itself, not just the container. Falling back to a tolerant re-encode "
            "(this re-compresses the video and may skip truly unrecoverable stretches)..."
        )
        log_progress(0.55)

        def on_reencode_progress(fraction):
            log_progress(0.55 + fraction * 0.4)

        try:
            tmp_path = reencode_repair(src_path, on_progress=on_reencode_progress)
            method = "re-encode (lossy, best-effort)"
        except Exception as exc:  # noqa: BLE001
            write_plugin_output(error=f"Both repair attempts failed — the file may be too badly damaged to recover: {exc}")
            return

    log_progress(0.95)
    final_path, removed_path = finalize_repaired_output(src_path, tmp_path, keep_original)

    rescan_target = [final_path]
    if removed_path and removed_path != final_path:
        rescan_target.append(os.path.dirname(removed_path))
    # Queued, not waited on: Stash runs one job at a time, so this scan
    # can't start until this task ends — and nothing below needs it.
    client.rescan_paths(rescan_target)

    try:
        existing_tag_ids = [t["id"] for t in scene.get("tags", [])]
        client.add_tag_to_scene(scene["id"], existing_tag_ids, repair_tag_id)
    except Exception as exc:  # noqa: BLE001
        log_warn(f"Repaired the file but couldn't tag the scene: {exc}")

    log_progress(1.0)
    summary = f"Repaired {scene_label(scene)} via {method}. New file: {os.path.basename(final_path)}."
    if keep_original:
        summary += " Original kept alongside it — check playback, then delete the original yourself once you're happy with it."
    log_info(summary)
    write_plugin_output(output=summary)


def run_convert_scene(client, args, done_tag_id):
    scene_id = args.get("scene_id")
    if not scene_id:
        write_plugin_output(error="convert_scene mode requires a scene_id argument")
        return

    crf = resolve_crf(args)
    scene = client.get_scene(scene_id)
    if not scene:
        write_plugin_output(error=f"No scene found with id {scene_id}")
        return
    label = scene_label(scene)
    log_info(f"Quality: CRF {crf}")

    keep_original = str(args.get("keep_original", "false")).lower() == "true"
    log_progress(0.05)

    def on_progress(fraction):
        # Reserve the tail end for tagging/rescanning/linking after the
        # encode itself finishes.
        log_progress(0.05 + fraction * 0.8)

    followups = []
    status = process_scene(client, scene, keep_original, done_tag_id, followups, crf=crf, on_progress=on_progress)
    queue_convert_followups(client, followups, f"Finish converting {scene_name(scene)}")
    log_progress(1.0)

    if status == "converted":
        write_plugin_output(output=f"{label} converted to H265.")
    elif status == "skipped":
        write_plugin_output(output=f"{label} skipped (already H265 or already converted).")
    else:
        write_plugin_output(error=f"{label}: {status}")


def run_convert_library(client, args, done_tag_id):
    keep_original = str(args.get("keep_original", "false")).lower() == "true"
    crf = resolve_crf(args)

    total = client.count_scenes()
    log_info(f"Scanning {total} scenes for non-H265 video (CRF {crf})...")

    # One scan and one attach task for the whole run, rather than a pair
    # per scene. Queued in `finally`, so files already converted still get
    # scanned and attached even if the run stops partway.
    followups = []
    try:
        _convert_library_pages(client, keep_original, done_tag_id, crf, total, followups)
    finally:
        queue_convert_followups(client, followups, "Finish converting library")


def _convert_library_pages(client, keep_original, done_tag_id, crf, total, followups):
    converted, skipped, failed = 0, 0, 0
    page, per_page = 1, 50
    processed = 0

    while True:
        scenes = client.find_scenes_page(page, per_page)
        if not scenes:
            break

        for scene in scenes:
            # Give this scene its own slice of the overall bar so a long
            # encode moves the progress bar smoothly instead of it sitting
            # frozen at the previous scene's boundary until this one ends.
            base = (processed / total) if total else 0.0
            slice_size = (1.0 / total) if total else 0.0

            def on_progress(fraction, base=base, slice_size=slice_size):
                if total:
                    log_progress(base + fraction * slice_size)

            status = process_scene(client, scene, keep_original, done_tag_id, followups, crf=crf, on_progress=on_progress)
            processed += 1
            if total:
                log_progress(processed / total)

            if status == "converted":
                converted += 1
            elif status == "skipped":
                skipped += 1
            else:
                failed += 1

        page += 1

    summary = f"Converted {converted}, skipped {skipped} (already H265/tagged), failed {failed}."
    log_info(summary)
    write_plugin_output(output=summary)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def read_plugin_input():
    raw = sys.stdin.read()
    if not raw.strip():
        return {"server_connection": {}, "args": {}}
    return json.loads(raw)


def write_plugin_output(output=None, error=None):
    result = {}
    if error:
        result["error"] = str(error)
    else:
        result["output"] = output or "ok"
    print(json.dumps(result))


def main():
    plugin_input = read_plugin_input()
    server_connection = plugin_input.get("server_connection", {})
    args = plugin_input.get("args", {}) or {}
    mode = args.get("mode", "convert_library")

    client = StashClient(server_connection)

    if mode == "split_scene":
        try:
            client.call("query { version { version } }")
        except Exception as exc:  # noqa: BLE001
            write_plugin_output(error=f"Could not reach Stash GraphQL API: {exc}")
            return
        run_split_scene(client, args)
        return

    if mode == "split_finalize":
        run_split_finalize(client, args)
        return

    if mode == "convert_finalize":
        run_convert_finalize(client, args)
        return

    if mode == "repair_scene":
        try:
            repair_tag_id = client.find_or_create_tag(REPAIR_TAG_NAME)
        except Exception as exc:  # noqa: BLE001
            write_plugin_output(error=f"Could not reach Stash GraphQL API: {exc}")
            return
        run_repair_scene(client, args, repair_tag_id)
        return

    try:
        done_tag_id = client.find_or_create_tag(DONE_TAG_NAME)
    except Exception as exc:  # noqa: BLE001
        write_plugin_output(error=f"Could not reach Stash GraphQL API: {exc}")
        return

    if mode == "convert_scene":
        run_convert_scene(client, args, done_tag_id)
    else:
        run_convert_library(client, args, done_tag_id)


if __name__ == "__main__":
    main()
