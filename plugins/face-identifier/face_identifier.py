"""Face Identifier — who's in a scene, by their faces.

Like starIdentifier (CommunityScripts), with a page to work in, and Visage
as a second opinion:

  - Learning: every performer's portrait in Stash is looked at once, the
    face in it (the largest) turned into a "face print" (OpenCV's SFace,
    128 numbers). Faces you confirm later ("that's her") are added to the
    performer's prints — so the more you confirm, the better it knows them.
  - A scene: frames spread over the video (not Stash's tiny preview
    thumbnails — real frames, a face is big enough there), the faces in
    them found (OpenCV's YuNet) and compared with the prints. Faces of the
    same unknown person are grouped.
  - Visage (optional, off by default): Stash's preview sprite sent to the
    Visage service (cc1234's face search on Hugging Face, or your own) —
    it knows the performers of StashDB / JavStash only.

Runs as a Stash task (the job queue: it survives the page being closed),
writing how far it is and the result into Stash's generated folder
(face-identifier/), where the dialog fetches it.

Needs OpenCV for the Python Stash runs (pip install opencv-python-headless
numpy); the two models (40 MB) are downloaded the first time.
"""

import base64
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

PLUGIN_ID = "faceIdentifier"
MODELS = {
    "yunet.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}
SAME_PERSON = 0.363  # SFace, cosine: from here on the same person (OpenCV's own figure)
GROUP = 0.42  # unknown faces this alike are put together
MIN_FACE = 40  # px: smaller faces aren't read
DEFAULT_FRAMES = 40
SURE = 0.45  # a match this alike, or in two frames or more: "found"; else "maybe"
LONG_DEAD = 1930
VISAGE_URL = "https://cc1234-stashface-onnx.hf.space"
LOG = sys.stderr


def info(text):
    LOG.write(f"\x01i\x02{text}\n")
    LOG.flush()


def progress(fraction):
    LOG.write(f"\x01p\x02{max(0.0, min(1.0, fraction)):.3f}\n")
    LOG.flush()


# -- Stash ---------------------------------------------------------------------------------------

class Stash:
    def __init__(self, conn):
        scheme = conn.get("Scheme", "http")
        host = conn.get("Host") or "localhost"
        if host in ("0.0.0.0", ""):
            host = "localhost"
        self.base = f"{scheme}://{host}:{conn.get('Port', 9999)}"
        self.headers = {}
        cookie = conn.get("SessionCookie") or {}
        if cookie.get("Name") and cookie.get("Value"):
            self.headers["Cookie"] = f"{cookie['Name']}={cookie['Value']}"
        if conn.get("ApiKey"):
            self.headers["ApiKey"] = conn["ApiKey"]

    def gql(self, query, variables=None):
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        req = urllib.request.Request(self.base + "/graphql", data=body, method="POST",
                                     headers={**self.headers, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode())
        if data.get("errors"):
            raise RuntimeError(f"Stash: {data['errors']}")
        return data["data"]

    def fetch(self, url):
        """A file from Stash (a performer's image, a sprite) — its address
        as Stash gave it, asked of this Stash."""
        path = urllib.parse.urlsplit(url)
        local = self.base + path.path + (f"?{path.query}" if path.query else "")
        req = urllib.request.Request(local, headers=self.headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()


def settings_of(stash):
    plugins = stash.gql("query { configuration { plugins general { generatedPath ffmpegPath } } }")["configuration"]
    general = plugins["general"]
    mine = (plugins["plugins"] or {}).get(PLUGIN_ID) or {}
    return mine, general


def folder(general, *parts):
    base = os.path.abspath(general.get("generatedPath") or "generated")
    path = os.path.join(base, "face-identifier", *parts)
    os.makedirs(path, exist_ok=True)
    return path


# -- the models ------------------------------------------------------------------------------------

def opencv():
    try:
        import cv2
        import numpy
    except ImportError:
        raise SystemExit(f"OpenCV isn't installed for the Python Stash uses ({sys.executable}). On the Stash server: "
                         f"{sys.executable} -m pip install opencv-python-headless numpy")
    if not hasattr(cv2, "FaceDetectorYN"):
        raise SystemExit("This OpenCV is too old (4.5.4 or newer needed): "
                         f"{sys.executable} -m pip install -U opencv-python-headless")
    return cv2, numpy


class Faces:
    def __init__(self, general):
        self.cv2, self.np = opencv()
        models = folder(general, "models")
        for name, url in MODELS.items():
            path = os.path.join(models, name)
            if not os.path.isfile(path) or os.path.getsize(path) < 100000:
                info(f"Downloading the face model {name} …")
                urllib.request.urlretrieve(url, path + ".part")
                os.replace(path + ".part", path)
        self.detector = self.cv2.FaceDetectorYN.create(os.path.join(models, "yunet.onnx"), "", (320, 320), 0.8, 0.3, 5000)
        self.recognizer = self.cv2.FaceRecognizerSF.create(os.path.join(models, "sface.onnx"), "")

    def decode(self, data):
        return self.cv2.imdecode(self.np.frombuffer(data, self.np.uint8), self.cv2.IMREAD_COLOR)

    def find(self, img, min_size=MIN_FACE):
        """[(box, print)] of the faces in a picture."""
        if img is None:
            return []
        h, w = img.shape[:2]
        if max(h, w) > 1600:  # big pictures: smaller first (the faces stay big enough)
            k = 1600 / max(h, w)
            img = self.cv2.resize(img, (int(w * k), int(h * k)))
            h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        _, found = self.detector.detect(img)
        out = []
        for f in [] if found is None else found:
            if f[2] < min_size or f[3] < min_size:
                continue
            aligned = self.recognizer.alignCrop(img, f)
            vec = self.recognizer.feature(aligned).flatten()
            vec = vec / (self.np.linalg.norm(vec) or 1)
            out.append(({"x": int(f[0]), "y": int(f[1]), "w": int(f[2]), "h": int(f[3]), "score": round(float(f[14]), 3)},
                        vec, img))
        return out

    def crop(self, img, box, height=112):
        """A small JPEG of a face (with a little around it), as a data URL."""
        m = int(box["w"] * 0.35)
        h, w = img.shape[:2]
        part = img[max(0, box["y"] - m):min(h, box["y"] + box["h"] + m), max(0, box["x"] - m):min(w, box["x"] + box["w"] + m)]
        if part.size == 0:
            return None
        k = height / part.shape[0]
        part = self.cv2.resize(part, (max(1, int(part.shape[1] * k)), height))
        ok, data = self.cv2.imencode(".jpg", part, [int(self.cv2.IMWRITE_JPEG_QUALITY), 82])
        return "data:image/jpeg;base64," + base64.b64encode(data.tobytes()).decode() if ok else None


# -- what it knows: the face prints ----------------------------------------------------------------

def index_path(general):
    return os.path.join(folder(general), "index.json")


def load_index(general):
    try:
        with open(index_path(general), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"performers": {}}


def save_index(general, index):
    path = index_path(general)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(index, f)
    os.replace(path + ".tmp", path)


def matrix(index, np):
    """(vectors, their performer ids) of everything known."""
    vecs, owners = [], []
    for pid, p in index["performers"].items():
        if p.get("died") and p["died"].isdigit() and int(p["died"]) < LONG_DEAD:
            continue  # died before films: not in a video (a composer's portrait, a painting)
        for v in ([p["portrait"]["vector"]] if p.get("portrait") else []) + (p.get("confirmed") or []):
            vecs.append(v)
            owners.append(pid)
    return (np.array(vecs, dtype=np.float32) if vecs else np.zeros((0, 128), np.float32)), owners


def learn(stash, general, log=info):
    """Every performer's portrait: its face print (those changed since)."""
    faces = Faces(general)
    index = load_index(general)
    performers = stash.gql("query { findPerformers(filter: { per_page: -1 }) { performers { id name image_path updated_at death_date } } }")["findPerformers"]["performers"]
    learnt, no_face, no_image, unchanged = 0, [], [], 0
    for i, p in enumerate(performers):
        progress(i / max(1, len(performers)))
        pid = str(p["id"])
        entry = index["performers"].setdefault(pid, {"name": p["name"], "portrait": None, "confirmed": []})
        entry["name"] = p["name"]
        entry["died"] = (p.get("death_date") or "")[:4] or None
        key = p.get("updated_at") or ""
        if entry.get("portrait_key") == key:
            unchanged += 1
            continue
        entry["portrait_key"] = key
        try:
            data = stash.fetch(p["image_path"]) if p.get("image_path") else b""
        except Exception:  # noqa: BLE001
            data = b""
        if len(data) <= 2000:  # 645 bytes: Stash's placeholder — no portrait
            entry["portrait"] = None
            no_image.append(p["name"])
            continue
        found = faces.find(faces.decode(data), min_size=24)
        if not found:
            entry["portrait"] = None
            no_face.append(p["name"])
            continue
        box, vec, _ = max(found, key=lambda f: f[0]["w"] * f[0]["h"])
        entry["portrait"] = {"vector": [round(float(x), 5) for x in vec]}
        learnt += 1
    # performers gone from Stash
    ids = {str(p["id"]) for p in performers}
    for pid in [k for k in index["performers"] if k not in ids]:
        index["performers"].pop(pid)
    save_index(general, index)
    progress(1)
    known = sum(1 for p in index["performers"].values() if p.get("portrait") or p.get("confirmed"))
    log(f"Faces learnt: {learnt} portrait(s) new or changed, {unchanged} unchanged; {known} performers known by face. "
        f"{len(no_image)} without a portrait; no face found in {len(no_face)} portrait(s)"
        + (f" (e.g. {', '.join(no_face[:8])} — an ensemble, a drawing …)" if no_face else "") + ".")
    return {"learnt": learnt, "unchanged": unchanged, "known": known, "no_face": no_face[:50], "no_image": len(no_image)}


# -- a scene ----------------------------------------------------------------------------------------

SCENE = """query($id: ID!) { findScene(id: $id) { id title paths { sprite vtt }
  files { path duration size mod_time } performers { id name image_path } } }"""


def frame_at(ffmpeg, path, at):
    out = subprocess.run([ffmpeg, "-v", "error", "-ss", f"{at:.2f}", "-i", path, "-frames:v", "1", "-an", "-sn",
                          "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"], capture_output=True, timeout=120)
    return out.stdout


def identify(stash, general, settings, scene_id, write_progress=None):
    faces = Faces(general)
    np = faces.np
    scene = stash.gql(SCENE, {"id": scene_id})["findScene"]
    if not scene or not scene.get("files"):
        raise SystemExit("The scene has no file.")
    f = scene["files"][0]
    duration = f.get("duration") or 0
    count = int(settings.get("framesPerScene") or DEFAULT_FRAMES)
    times = [duration * (0.02 + 0.96 * i / max(1, count - 1)) for i in range(count)] if duration else [0]
    ffmpeg = general.get("ffmpegPath") or "ffmpeg"
    index = load_index(general)
    known, owners = matrix(index, np)
    seen = []  # (time, box, vector, crop)
    for i, at in enumerate(times):
        progress(i / len(times))
        if write_progress:
            write_progress(i, len(times))
        img = faces.decode(frame_at(ffmpeg, f["path"], at)) if at is not None else None
        for box, vec, shown in faces.find(img):
            seen.append({"t": round(at, 1), "box": box, "vector": vec, "crop": faces.crop(shown, box)})
    # who: each face against every print — the best performer, if alike enough
    by_performer, unknown = {}, []
    for n, s in enumerate(seen):
        s["id"] = n
        if len(owners):
            scores = known @ s["vector"]
            best = {}
            for owner, score in zip(owners, scores):
                best[owner] = max(best.get(owner, -1), float(score))
            pid, score = max(best.items(), key=lambda kv: kv[1])
            if score >= SAME_PERSON:
                hit = by_performer.setdefault(pid, {"performer_id": pid, "name": index["performers"][pid]["name"],
                                                    "faces": [], "best": 0, "crop": None})
                hit["faces"].append(n)
                if score > hit["best"]:
                    hit["best"], hit["crop"] = round(score, 3), s["crop"]
                continue
        unknown.append(s)
    # the unknown: the same person's faces together
    groups = []
    for s in unknown:
        for g in groups:
            if float(g["rep"] @ s["vector"]) >= GROUP:
                g["faces"].append(s["id"])
                if s["box"]["w"] > g["size"]:
                    g["crop"], g["size"] = s["crop"], s["box"]["w"]
                break
        else:
            groups.append({"rep": s["vector"], "faces": [s["id"]], "crop": s["crop"], "size": s["box"]["w"]})
    in_scene = {str(p["id"]) for p in scene.get("performers") or []}
    found = sorted(by_performer.values(), key=lambda h: (-len(h["faces"]), -h["best"]))
    for h in found:
        h["count"] = len(h["faces"])
        h["in_scene"] = h["performer_id"] in in_scene
        h["times"] = sorted({seen[n]["t"] for n in h["faces"]})
        h["sure"] = h["count"] >= 2 or h["best"] >= SURE
    groups = [g for g in groups if len(g["faces"]) >= 2 and g["size"] >= 50 or g["size"] >= 110]  # once and small: background
    groups.sort(key=lambda g: -len(g["faces"]))
    return {
        "scene_id": str(scene_id),
        "frames": len(times), "faces": len(seen),
        "found": found,
        "unknown": [{"group": i, "faces": g["faces"], "count": len(g["faces"]), "crop": g["crop"],
                     "times": sorted({seen[n]["t"] for n in g["faces"]})} for i, g in enumerate(groups[:16])],
        "vectors": {str(s["id"]): [round(float(x), 5) for x in s["vector"]] for s in seen},
        "known_performers": sum(1 for p in index["performers"].values() if p.get("portrait") or p.get("confirmed")),
        "signature": signature(f, index_path(general)),
        "made": datetime.datetime.now().isoformat(timespec="seconds"),
    }


def signature(f, index_file):
    try:
        index_time = os.path.getmtime(index_file)
    except OSError:
        index_time = 0
    return hashlib.sha1(f"{f.get('path')}|{f.get('size')}|{f.get('mod_time')}|{index_time}".encode()).hexdigest()[:16]


def confirm(general, performer_id, name, vectors):
    """Faces said to be someone's: added to their prints."""
    index = load_index(general)
    entry = index["performers"].setdefault(str(performer_id), {"name": name, "portrait": None, "confirmed": []})
    entry["confirmed"] = (entry.get("confirmed") or []) + [list(v) for v in vectors]
    entry["confirmed"] = entry["confirmed"][-40:]  # the last 40 are enough
    save_index(general, index)
    return {"confirmed": len(vectors), "prints": len(entry["confirmed"]) + (1 if entry.get("portrait") else 0)}


# -- Visage -----------------------------------------------------------------------------------------

def visage(stash, settings, scene_id):
    """Visage's face search on the scene's preview sprite: [{name, id,
    source, confidence, url, image, in_stash}]."""
    base = (settings.get("visageUrl") or VISAGE_URL).rstrip("/")
    scene = stash.gql(SCENE, {"id": scene_id})["findScene"]
    paths = scene.get("paths") or {}
    if not paths.get("sprite") or not paths.get("vtt"):
        raise SystemExit("The scene has no preview sprite yet (Stash's Generate → Sprites).")
    sprite, vtt = stash.fetch(paths["sprite"]), stash.fetch(paths["vtt"])

    def upload(data, name):
        boundary = uuid.uuid4().hex
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{name}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{base}/gradio_api/upload", data=body, method="POST",
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())[0]
    files = [{"path": upload(sprite, "sprite.jpg"), "meta": {"_type": "gradio.FileData"}},
             {"path": upload(vtt, "thumbs.vtt"), "meta": {"_type": "gradio.FileData"}}]
    threshold = float(settings.get("visageThreshold") or 70)
    req = urllib.request.Request(f"{base}/gradio_api/call/identify_sprite_performers", method="POST",
                                 data=json.dumps({"data": files + [20]}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        event = json.loads(r.read().decode())["event_id"]
    result = None
    with urllib.request.urlopen(f"{base}/gradio_api/call/identify_sprite_performers/{event}", timeout=600) as r:
        for line in r.read().decode("utf-8", "replace").splitlines():
            if line.startswith("data: "):
                try:
                    value = json.loads(line[6:])
                except ValueError:
                    continue
                value = value[0] if isinstance(value, list) and len(value) == 1 else value
                if isinstance(value, dict) and "progress" in value:
                    continue
                result = value
    if isinstance(result, dict) and result.get("error"):
        return {"matches": [], "note": result["error"]}
    # performers in what came back (any nesting), with their confidence
    out = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("name") and (o.get("performer_url") or o.get("source_urls")):
                conf = float(o.get("confidence") or 0)
                key = o.get("id") or o["name"]
                if conf >= threshold and (key not in out or conf > out[key]["confidence"]):
                    out[key] = {"name": o["name"], "id": o.get("id"), "source": o.get("source"), "confidence": conf,
                                "url": o.get("performer_url"), "image": o.get("image"), "hits": o.get("hits")}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(result)
    matches = sorted(out.values(), key=lambda m: -m["confidence"])
    # in Stash already? by its StashDB id, else by name
    for m in matches:
        found = stash.gql('query($n: String!) { findPerformers(performer_filter: { name: { value: $n, modifier: EQUALS } }, '
                          'filter: { per_page: 1 }) { performers { id name } } }', {"n": m["name"]})["findPerformers"]["performers"]
        m["in_stash"] = found[0] if found else None
    note = "" if matches else f"Visage found nobody with {threshold:.0f} % confidence or more — it knows StashDB's and JavStash's performers only."
    return {"matches": matches, "note": note}


# -- the job: a scene as a Stash task --------------------------------------------------------------

def result_paths(general, scene_id):
    name = re.sub(r"\W", "", str(scene_id))
    base = folder(general, "results")
    return os.path.join(base, f"{name}.json"), os.path.join(base, f"{name}.progress.json")


def write_json(path, value):
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(value, f)
    os.replace(path + ".tmp", path)


def start(stash, general, settings, scene_id, again=False):
    """The result if there's one for this file and these prints; else a Stash
    task is queued (one per scene) and {"running": true, "job"} returned."""
    result_file, progress_file = result_paths(general, scene_id)
    scene = stash.gql(SCENE, {"id": scene_id})["findScene"]
    if not again:
        try:
            with open(result_file, encoding="utf-8") as f:
                result = json.load(f)
            if scene and scene.get("files") and result.get("signature") == signature(scene["files"][0], index_path(general)):
                result.pop("vectors", None)
                in_scene = {str(p["id"]) for p in scene.get("performers") or []}
                for h in result.get("found") or []:
                    h["in_scene"] = h["performer_id"] in in_scene
                return result
        except (OSError, ValueError):
            pass
    description = f"Who's in it: {(scene or {}).get('title') or os.path.basename(((scene or {}).get('files') or [{}])[0].get('path') or '')}"
    queued = next((j for j in stash.gql("query { jobQueue { id description status } }").get("jobQueue") or []
                   if j["description"].endswith(description) and j["status"] in ("READY", "RUNNING")), None)
    job = queued["id"] if queued else stash.gql(
        "mutation($id: ID!, $d: String, $a: Map) { runPluginTask(plugin_id: $id, description: $d, args_map: $a) }",
        {"id": PLUGIN_ID, "d": description, "a": {"mode": "identify_job", "scene_id": str(scene_id)}})["runPluginTask"]
    write_json(progress_file, {"done": 0, "total": 0, "phase": "queued", "updated": time.time()})
    return {"running": True, "job": job}


def identify_job(stash, general, settings, scene_id):
    result_file, progress_file = result_paths(general, scene_id)

    def say(done, total):
        write_json(progress_file, {"done": done, "total": total, "phase": "frames", "updated": time.time()})
    try:
        result = identify(stash, general, settings, scene_id, say)
    finally:
        write_json(progress_file, {"done": 1, "total": 1, "phase": "done", "updated": time.time()})
    write_json(result_file, result)
    names = ", ".join(f"{h['name']} ({h['count']}×)" for h in result["found"][:6]) or "nobody known"
    info(f"Faces in scene {scene_id}: {result['faces']} in {result['frames']} frames — {names}; {len(result['unknown'])} unknown.")
    return {"found": len(result["found"]), "unknown": len(result["unknown"])}


def status(general, scene_id):
    _, progress_file = result_paths(general, scene_id)
    try:
        with open(progress_file, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def confirm_faces(stash, general, scene_id, performer_id, face_ids):
    result_file, _ = result_paths(general, scene_id)
    with open(result_file, encoding="utf-8") as f:
        result = json.load(f)
    vectors = [result["vectors"][str(i)] for i in face_ids if str(i) in result["vectors"]]
    name = stash.gql("query($id: ID!) { findPerformer(id: $id) { name } }", {"id": performer_id})["findPerformer"]["name"]
    out = confirm(general, performer_id, name, vectors)
    # the scene's result stays valid: the index changed only by what was just said
    sig = result.get("signature")
    scene = stash.gql(SCENE, {"id": scene_id})["findScene"]
    if scene and scene.get("files") and sig:
        result["signature"] = signature(scene["files"][0], index_path(general))
        write_json(result_file, result)
    return out


# -- the tag workflow (as starIdentifier) ------------------------------------------------------------

def tagged(stash, general, settings, log=info):
    """Scenes tagged "Identify faces": performers recognised in at least two
    frames with a clear likeness are added; the tag is taken off."""
    tag_name = (settings.get("tagToIdentify") or "Identify faces").strip()
    tags = stash.gql('query($n: String!) { findTags(tag_filter: { name: { value: $n, modifier: EQUALS } }) { tags { id } } }',
                     {"n": tag_name})["findTags"]["tags"]
    if not tags:
        log(f"No tag “{tag_name}” — tag the scenes to look at with it.")
        return {"scenes": 0}
    tid = tags[0]["id"]
    scenes = stash.gql("query($t: [ID!]) { findScenes(scene_filter: { tags: { value: $t, modifier: INCLUDES } }, filter: { per_page: -1 }) "
                       "{ scenes { id title performers { id } tags { id } } } }", {"t": [tid]})["findScenes"]["scenes"]
    sure = float(settings.get("autoAddLikeness") or 0.45)
    added_total = 0
    for i, s in enumerate(scenes):
        log(f"[{i + 1}/{len(scenes)}] {s.get('title') or s['id']} …")
        result = identify(stash, general, settings, s["id"])
        write_json(result_paths(general, s["id"])[0], result)
        have = {str(p["id"]) for p in s["performers"]}
        add = [h["performer_id"] for h in result["found"] if h["count"] >= 2 and h["best"] >= sure and h["performer_id"] not in have]
        # (only the sure ones: seen twice and clearly alike)
        stash.gql("mutation($i: SceneUpdateInput!) { sceneUpdate(input: $i) { id } }",
                  {"i": {"id": s["id"], "performer_ids": list(have) + add, "tag_ids": [t["id"] for t in s["tags"] if t["id"] != tid]}})
        added_total += len(add)
        if add:
            log(f"   added: {', '.join(h['name'] for h in result['found'] if h['performer_id'] in add)}")
    log(f"Done: {len(scenes)} scene(s), {added_total} performer(s) added.")
    return {"scenes": len(scenes), "added": added_total}


# -- entry ----------------------------------------------------------------------------------------

def main():
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    args = payload.get("args") or {}
    stash = Stash(payload.get("server_connection") or {})
    try:
        settings, general = settings_of(stash)
        mode = args.get("mode")
        if mode == "learn":
            output = learn(stash, general)
        elif mode == "start":
            output = start(stash, general, settings, args.get("scene_id"), str(args.get("again") or "") == "true")
        elif mode == "identify_job":
            output = identify_job(stash, general, settings, args.get("scene_id"))
        elif mode == "status":
            output = status(general, args.get("scene_id"))
        elif mode == "confirm":
            output = confirm_faces(stash, general, args.get("scene_id"), args.get("performer_id"),
                                   [int(x) for x in str(args.get("faces") or "").split(",") if x.strip().isdigit()])
        elif mode == "visage":
            output = visage(stash, settings, args.get("scene_id"))
        elif mode == "tagged":
            output = tagged(stash, general, settings)
        elif mode == "check":
            opencv()
            index = load_index(general)
            output = {"ok": True, "known": sum(1 for p in index["performers"].values() if p.get("portrait") or p.get("confirmed"))}
        else:
            raise SystemExit(f"Unknown mode {mode}")
        print(json.dumps({"output": output}))
    except SystemExit as exc:
        print(json.dumps({"error": str(exc.code)}))
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))


if __name__ == "__main__":
    main()
