#!/usr/bin/env python3
"""
Advanced File Operations — a Stash plugin.

Three video tools for your Stash library:
  - H265 conversion: re-encodes non-HEVC video to H.265 at a "visually
    lossless" CRF setting, per-scene or across the whole library.
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
       up under Settings > Tasks > Plugin Tasks; the per-scene buttons
       (Convert to H265 / Split at Markers / Repair File) show up on each
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
CRF_VALUE = 18

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

# Name of the tag applied to scenes after a successful repair.
REPAIR_TAG_NAME = "File Repaired"


# ---------------------------------------------------------------------------
# Stash plugin log protocol
# ---------------------------------------------------------------------------
# Stash reads plugin stderr line by line. A line that starts with an SOH
# (\x01) byte, then one of t/d/i/w/e/p, then a space, is parsed as a log line
# at that level and shown in the plugin log in the UI. Progress lines use
# "p" and a value 0.0-1.0.

def _log(level, message):
    sys.stderr.write(f"\x01{level} {message}\n")
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

    def wait_for_job(self, job_id, timeout=1800, poll_interval=3):
        """
        Polls Stash's job queue until the given job id finishes (or we time
        out). If this Stash version doesn't expose findJob the way we
        expect, falls back to just waiting a fixed buffer instead of
        failing the whole run over it.
        """
        done_statuses = {"FINISHED", "CANCELLED", "STOPPED", "FAILED"}
        waited = 0
        while waited < timeout:
            try:
                data = self.call(
                    """
                    query($id: ID!) {
                      findJob(input: { id: $id }) { id status }
                    }
                    """,
                    {"id": job_id},
                )
                job = data.get("findJob")
                if not job or job.get("status") in done_statuses:
                    return
            except Exception as exc:  # noqa: BLE001
                log_warn(f"Couldn't poll scan job status ({exc}); waiting a fixed buffer instead")
                time.sleep(poll_interval * 5)
                return
            time.sleep(poll_interval)
            waited += poll_interval
        log_warn("Timed out waiting for the scan job to finish; continuing anyway")

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

    def rescan_paths(self, paths):
        """Triggers a scan and returns whatever metadataScan resolves to —
        a job id string on Stash versions with a job queue, or a plain
        boolean on older ones."""
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


def transcode_to_h265(src_path):
    """
    Encodes src_path to H.265 in a temp file, then returns that temp path.
    Raises on failure. Caller is responsible for moving/cleaning up.
    """
    if not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)

    tmp_dir = tempfile.gettempdir()
    fd, tmp_path = tempfile.mkstemp(suffix=OUTPUT_EXT, dir=tmp_dir)
    os.close(fd)

    cmd = [
        FFMPEG_BIN, "-y",
        "-i", src_path,
        "-map", "0:v:0", "-map", "0:a?", "-map", "0:s?",
        "-c:v", "libx265",
        "-preset", X265_PRESET,
        "-crf", str(CRF_VALUE),
        "-tag:v", "hvc1",          # keeps QuickTime/Apple players happy
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-c:s", "copy",
        tmp_path,
    ]

    log_info(f"Transcoding: {src_path}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
        # Common fallback: source has a subtitle stream ffmpeg can't copy
        # into mp4 (e.g. PGS). Retry once without subtitles.
        log_warn("First encode attempt failed, retrying without subtitle copy...")
        cmd_no_subs = [c for c in cmd if c not in ("-s", "copy")]
        cmd_no_subs = [
            FFMPEG_BIN, "-y", "-i", src_path,
            "-map", "0:v:0", "-map", "0:a?",
            "-c:v", "libx265", "-preset", X265_PRESET, "-crf", str(CRF_VALUE),
            "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            tmp_path,
        ]
        proc = subprocess.run(cmd_no_subs, capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
            raise RuntimeError(f"ffmpeg failed on {src_path}: {proc.stderr[-2000:]}")

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


def process_scene(client, scene, keep_original, done_tag_id):
    """
    Converts one scene's primary video file to H265 if it needs it.
    Returns a short status string: "converted" / "skipped" / "failed: <why>".
    Raises nothing — failures are reported in the return value so a batch
    run can keep going.
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
    try:
        tmp_path = transcode_to_h265(src_path)
        final_path, removed_path = finalize_output(src_path, tmp_path, keep_original)

        existing_tag_ids = [t["id"] for t in scene.get("tags", [])]
        client.add_tag_to_scene(scene["id"], existing_tag_ids, done_tag_id)

        rescan_paths = [final_path]
        if removed_path and removed_path != final_path:
            rescan_paths.append(os.path.dirname(removed_path))
        client.rescan_paths(rescan_paths)

        log_info(f"Converted scene {scene['id']}: {os.path.basename(src_path)}")
        return "converted"
    except Exception as exc:  # noqa: BLE001
        log_error(f"Failed on scene {scene['id']} ({src_path}): {exc}")
        return f"failed: {exc}"


def scan_and_wait(client, paths):
    job_id = client.rescan_paths(paths)
    if isinstance(job_id, str):
        client.wait_for_job(job_id)
    else:
        # Older Stash versions scan synchronously enough, or return a plain
        # boolean; give the library a moment to settle either way.
        time.sleep(10)


# ---------------------------------------------------------------------------
# Splitting a scene at its markers
# ---------------------------------------------------------------------------

def get_duration_seconds(path):
    result = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=60,
    )
    return float(result.stdout.strip())


def cut_segment(src_path, start, end, out_path, accurate):
    duration = end - start
    if accurate:
        # Re-encodes so the cut lands exactly on the marker, at the cost of
        # time and a second generation of lossy compression.
        cmd = [
            FFMPEG_BIN, "-y",
            "-i", src_path, "-ss", str(start), "-t", str(duration),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            out_path,
        ]
    else:
        # Stream-copy: no re-encode, no quality loss, but the cut snaps to
        # the nearest keyframe so it can land a little before/after the
        # exact marker time.
        cmd = [
            FFMPEG_BIN, "-y",
            "-ss", str(start), "-i", src_path, "-t", str(duration),
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            out_path,
        ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError(f"ffmpeg failed cutting [{start:.2f}s, {end:.2f}s): {proc.stderr[-1500:]}")


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
    cut_seconds_arg = (args.get("cut_seconds") or "").strip()
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
    segments = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if end - start >= MIN_SEGMENT_SECONDS:
            segments.append((start, end))

    if len(segments) < 2:
        write_plugin_output(error="Markers didn't produce more than one usable segment; nothing to split")
        return

    base_dir = os.path.dirname(src_path)
    base_name, ext = os.path.splitext(os.path.basename(src_path))
    log_info(f"Splitting '{base_name}{ext}' into {len(segments)} part(s) at {len(cut_points)} marker(s)...")

    out_paths = []
    try:
        for idx, (start, end) in enumerate(segments, start=1):
            log_progress((idx - 1) / len(segments) * 0.5)
            out_path = os.path.join(base_dir, f"{base_name}.part{idx}{ext}")
            cut_segment(src_path, start, end, out_path, accurate)
            out_paths.append((out_path, start, end))
    except Exception as exc:  # noqa: BLE001
        for p, _, _ in out_paths:
            if os.path.isfile(p):
                os.remove(p)
        write_plugin_output(error=f"Splitting failed, no changes made: {exc}")
        return

    log_info("Scanning the new split files into Stash (this can take a bit)...")
    scan_and_wait(client, [p for p, _, _ in out_paths])
    log_progress(0.6)

    performer_ids = [p["id"] for p in scene.get("performers") or []]
    tag_ids = [t["id"] for t in scene.get("tags") or []]
    studio_id = scene["studio"]["id"] if scene.get("studio") else None
    original_title = scene.get("title") or base_name

    created, needs_follow_up = 0, 0
    for idx, (out_path, start, end) in enumerate(out_paths, start=1):
        log_progress(0.6 + (idx / len(out_paths)) * 0.4)

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
                title=f"{original_title} (part {idx})",
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

        is_last = idx == len(out_paths)
        segment_markers = [
            m for m in markers
            if start <= float(m["seconds"]) < end
            or (is_last and float(m["seconds"]) == end)
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
        log_info(f"Part {idx}: scene {new_scene_id} ({os.path.basename(out_path)}), {marker_count} marker(s) carried over")

    if not keep_original:
        try:
            os.remove(src_path)
            scan_and_wait(client, [base_dir])
            log_info(f"Removed original file: {src_path}")
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Split succeeded but couldn't remove the original file: {exc}")

    summary = f"Split into {len(out_paths)} part(s): {created} fully set up, {needs_follow_up} need a manual look."
    log_info(summary)
    write_plugin_output(output=summary)


# ---------------------------------------------------------------------------
# Repairing a corrupt file
# ---------------------------------------------------------------------------

def make_temp_output(ext=OUTPUT_EXT):
    fd, tmp_path = tempfile.mkstemp(suffix=ext, dir=tempfile.gettempdir())
    os.close(fd)
    return tmp_path


def detect_corruption(path, timeout=1800):
    """
    Decodes the whole file (video, audio, everything) through ffmpeg,
    throwing the output away, and watches for decode errors. This is the
    same technique "verify my rip" scripts use — it's slower than just
    opening the file (which only reads the container), but it's the only
    reliable way to catch mid-file corruption rather than just a broken
    header. Returns (is_corrupt, detail_message).
    """
    cmd = [FFMPEG_BIN, "-v", "error", "-xerror", "-i", path, "-map", "0", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return True, "Corruption check timed out (very large or very slow file) — treating it as needing repair"

    stderr = proc.stderr.strip()
    if proc.returncode != 0 or stderr:
        return True, (stderr or f"ffmpeg exited with code {proc.returncode}")
    return False, ""


def remux_repair(src_path):
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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = (
        proc.returncode == 0
        and os.path.isfile(tmp_path)
        and os.path.getsize(tmp_path) > 0
        and probe_ok(tmp_path)
    )
    if not ok:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        return None
    return tmp_path


def reencode_repair(src_path):
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
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = (
        proc.returncode == 0
        and os.path.isfile(tmp_path)
        and os.path.getsize(tmp_path) > 0
        and probe_ok(tmp_path)
    )
    if not ok:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError(f"Re-encode repair failed: {proc.stderr[-1500:]}")
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

    log_info(f"Checking '{os.path.basename(src_path)}' for corruption (this decodes the whole file, so it can take a while)...")
    log_progress(0.05)
    is_corrupt, detail = detect_corruption(src_path)

    if not is_corrupt and not force:
        write_plugin_output(output="No corruption detected — the file decodes cleanly, nothing to repair.")
        return
    if is_corrupt:
        log_warn(f"Corruption detected: {detail[:800]}")
    else:
        log_info("No corruption detected, but repairing anyway since force was requested.")
    log_progress(0.15)

    log_info("Attempting a lossless remux repair first...")
    tmp_path = remux_repair(src_path)
    method = "lossless remux"

    if tmp_path is None:
        log_warn(
            "Remux alone didn't produce a clean file, so the damage is in the stream "
            "data itself, not just the container. Falling back to a tolerant re-encode "
            "(this re-compresses the video and may skip truly unrecoverable stretches)..."
        )
        log_progress(0.3)
        try:
            tmp_path = reencode_repair(src_path)
            method = "re-encode (lossy, best-effort)"
        except Exception as exc:  # noqa: BLE001
            write_plugin_output(error=f"Both repair attempts failed — the file may be too badly damaged to recover: {exc}")
            return

    log_progress(0.8)
    final_path, removed_path = finalize_repaired_output(src_path, tmp_path, keep_original)

    rescan_target = [final_path]
    if removed_path and removed_path != final_path:
        rescan_target.append(os.path.dirname(removed_path))
    scan_and_wait(client, rescan_target)

    try:
        existing_tag_ids = [t["id"] for t in scene.get("tags", [])]
        client.add_tag_to_scene(scene["id"], existing_tag_ids, repair_tag_id)
    except Exception as exc:  # noqa: BLE001
        log_warn(f"Repaired the file but couldn't tag the scene: {exc}")

    log_progress(1.0)
    summary = f"Repaired via {method}. New file: {os.path.basename(final_path)}."
    if keep_original:
        summary += " Original kept alongside it — check playback, then delete the original yourself once you're happy with it."
    log_info(summary)
    write_plugin_output(output=summary)


def run_convert_scene(client, args, done_tag_id):
    scene_id = args.get("scene_id")
    if not scene_id:
        write_plugin_output(error="convert_scene mode requires a scene_id argument")
        return

    log_info(f"Converting single scene {scene_id} to H265...")
    scene = client.get_scene(scene_id)
    if not scene:
        write_plugin_output(error=f"No scene found with id {scene_id}")
        return

    keep_original = str(args.get("keep_original", "false")).lower() == "true"
    log_progress(0.1)
    status = process_scene(client, scene, keep_original, done_tag_id)
    log_progress(1.0)

    if status == "converted":
        write_plugin_output(output=f"Scene {scene_id} converted to H265.")
    elif status == "skipped":
        write_plugin_output(output=f"Scene {scene_id} skipped (already H265 or already converted).")
    else:
        write_plugin_output(error=f"Scene {scene_id}: {status}")


def run_convert_library(client, args, done_tag_id):
    keep_original = str(args.get("keep_original", "false")).lower() == "true"

    total = client.count_scenes()
    log_info(f"Scanning {total} scenes for non-H265 video...")

    converted, skipped, failed = 0, 0, 0
    page, per_page = 1, 50
    processed = 0

    while True:
        scenes = client.find_scenes_page(page, per_page)
        if not scenes:
            break

        for scene in scenes:
            processed += 1
            if total:
                log_progress(processed / total)

            status = process_scene(client, scene, keep_original, done_tag_id)
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
