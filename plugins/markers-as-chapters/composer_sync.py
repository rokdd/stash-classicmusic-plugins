"""Composers kept in step between a scene and its chapters (markers).

  - Chapters → scene: a chapter's composer (a tag under "Composers", the
    first of "Fill in tags under") whose performer isn't on the scene yet
    is added to the scene's performers.
  - Scene → chapters: when the scene has exactly one composer, a chapter
    without any composer gets that composer's tag. If the scene's composer
    changes, the chapters that got it automatically follow.
  - What you take away yourself stays away: a composer removed from a
    chapter isn't added to that chapter again, a performer removed from the
    scene isn't added to that scene again.

A composer tag belongs to a performer of the same name (or one of the tag's
aliases) — the tags Tag Improvements keeps for every composer.

Run by the hooks (a scene or a marker created or saved) and the task
"Composers of scenes and chapters in step (all scenes)". What was added
automatically, and what was taken away, is kept in .composer-sync.json in
the plugin's folder: {"markers": {id: {"auto": [tag ids], "removed": [tag
ids]}}, "scenes": {id: {"auto": [performer ids], "removed": [performer ids]}}}.
"""

import json
import os
import threading
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, ".composer-sync.json")
_lock = threading.Lock()

SCENE = """query($id: ID!) { findScene(id: $id) { id
  performers { id name alias_list }
  scene_markers { id tags { id name } } } }"""


def plain(text):
    text = unicodedata.normalize("NFKD", text or "")
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).lower().split())


def load():
    try:
        with open(RECORD, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.setdefault("markers", {})
    data.setdefault("scenes", {})
    return data


def save(data):
    tmp = RECORD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, RECORD)


def composer_parent(settings):
    raw = (settings.get("suggestTagsUnder") or "").strip() or "Composers, Soloists"
    names = [n.strip() for n in raw.split(",") if n.strip() and n.strip() != "-"]
    return names[0] if names else None


def composer_tags(gql, settings):
    """{tag id: tag} below the composers' parent tag."""
    parent_name = composer_parent(settings)
    if not parent_name:
        return {}
    parent = gql('query($n: String!) { findTags(tag_filter: { name: { value: $n, modifier: EQUALS } }, '
                 'filter: { per_page: 1 }) { tags { id } } }', {"n": parent_name})["findTags"]["tags"]
    if not parent:
        return {}
    tags = gql("query($ids: [ID!]) { findTags(tag_filter: { parents: { value: $ids, modifier: INCLUDES, depth: -1 } }, "
               "filter: { per_page: -1 }) { tags { id name aliases } } }", {"ids": [parent[0]["id"]]})["findTags"]["tags"]
    return {str(t["id"]): t for t in tags}


def names_of_tag(tag):
    return {plain(n) for n in [tag["name"], *(tag.get("aliases") or [])] if n}


def find_performer(gql, tag, cache):
    """The performer a composer tag belongs to (same name or alias), or None."""
    if tag["id"] in cache:
        return cache[tag["id"]]
    found = None
    for name in [tag["name"], *(tag.get("aliases") or [])]:
        hits = gql('query($n: String!) { findPerformers(performer_filter: { name: { value: $n, modifier: EQUALS } }, '
                   'filter: { per_page: 2 }) { performers { id name } } }', {"n": name})["findPerformers"]["performers"]
        if len(hits) == 1:
            found = hits[0]
            break
    cache[tag["id"]] = found
    return found


def sync_scene(gql, settings, scene_id, log=lambda line: None, tags=None):
    """Brings one scene and its chapters in step. Returns what it changed."""
    scene = (gql(SCENE, {"id": scene_id}) or {}).get("findScene")
    if not scene:
        return {}
    tags = tags if tags is not None else composer_tags(gql, settings)
    if not tags:
        return {}
    sid = str(scene["id"])
    performer_cache = {}
    with _lock:
        record = load()
        srec = record["scenes"].setdefault(sid, {"auto": [], "removed": []})
        performers = {str(p["id"]): p for p in scene.get("performers") or []}
        # performers the scene had last time and hasn't now: taken away by
        # hand (added automatically or not) — not added to it again
        for pid in set(srec.get("seen") or []) | set(srec["auto"]):
            if pid not in performers:
                if pid in srec["auto"]:
                    srec["auto"].remove(pid)
                if pid not in srec["removed"]:
                    srec["removed"].append(pid)
        # the scene's composers: its performers that have a composer tag
        tag_of_performer = {}
        for tid, tag in tags.items():
            for p in performers.values():
                if names_of_tag(tag) & {plain(p["name"]), *(plain(a) for a in p.get("alias_list") or [])}:
                    tag_of_performer[str(p["id"])] = tid
        markers = scene.get("scene_markers") or []
        changes = {"performers_added": [], "markers_tagged": 0, "markers_replaced": 0}

        # chapters → scene (not the tags the chapters got from the scene: when
        # the scene's composer changes, those follow it — they don't bring
        # the old one back)
        add = []
        for m in markers:
            given = (record["markers"].get(str(m["id"])) or {}).get("auto") or []
            for t in m.get("tags") or []:
                tid = str(t["id"])
                if tid not in tags or tid in tag_of_performer.values() or tid in given:
                    continue
                p = find_performer(gql, tags[tid], performer_cache)
                if p and str(p["id"]) not in performers and str(p["id"]) not in srec["removed"] and str(p["id"]) not in add:
                    add.append(str(p["id"]))
                    tag_of_performer[str(p["id"])] = tid
                    changes["performers_added"].append(p["name"])
        if add:
            gql("mutation($i: SceneUpdateInput!) { sceneUpdate(input: $i) { id } }",
                {"i": {"id": sid, "performer_ids": list(performers) + add}})
            srec["auto"] += [pid for pid in add if pid not in srec["auto"]]
            log(f"Scene {sid}: composer{'s' if len(add) > 1 else ''} of its chapters added — {', '.join(changes['performers_added'])}")

        # scene → chapters: only with exactly one composer (else it's not clear which)
        scene_composers = sorted(set(tag_of_performer.values()))
        only = scene_composers[0] if len(scene_composers) == 1 else None
        for m in markers:
            mid = str(m["id"])
            mrec = record["markers"].setdefault(mid, {"auto": [], "removed": []})
            have = [str(t["id"]) for t in m.get("tags") or []]
            # added automatically and gone now: taken away by hand
            for tid in list(mrec["auto"]):
                if tid not in have:
                    mrec["auto"].remove(tid)
                    if tid not in mrec["removed"]:
                        mrec["removed"].append(tid)
            composers_here = [tid for tid in have if tid in tags]
            new = None
            if not composers_here and only and only not in mrec["removed"]:
                new = have + [only]
                mrec["auto"].append(only)
                changes["markers_tagged"] += 1
            elif only and composers_here and set(composers_here) <= set(mrec["auto"]) and only not in composers_here \
                    and only not in mrec["removed"]:
                # the scene's composer changed: the one added automatically follows
                new = [tid for tid in have if tid not in composers_here] + [only]
                mrec["auto"] = [only]
                changes["markers_replaced"] += 1
            if new is not None:
                gql("mutation($i: SceneMarkerUpdateInput!) { sceneMarkerUpdate(input: $i) { id } }",
                    {"i": {"id": mid, "tag_ids": new}})
        if changes["markers_tagged"] or changes["markers_replaced"]:
            log(f"Scene {sid}: the scene's composer ({tags[only]['name']}) given to {changes['markers_tagged']} chapter(s)"
                + (f", {changes['markers_replaced']} changed to it" if changes["markers_replaced"] else ""))
        srec["seen"] = list(performers) + [pid for pid in add if pid not in performers]
        # tidy: nothing to remember for a marker
        for mid in [k for k, v in record["markers"].items() if not v["auto"] and not v["removed"]]:
            record["markers"].pop(mid, None)
        save(record)
    return changes


def hook(gql, settings, context, log=lambda line: None):
    """Scene.Update.Post, SceneMarker.Create.Post / Update.Post."""
    kind = context.get("type", "")
    if kind.startswith("SceneMarker.Destroy"):
        return {}
    if kind.startswith("SceneMarker."):
        # Stash's marker form (and the chapter editor) send the scene with it
        scene_id = (context.get("input") or {}).get("scene_id")
        if not scene_id:
            return {}
    elif kind.startswith("Scene."):
        scene_id = context.get("id")
    else:
        return {}
    return sync_scene(gql, settings, scene_id, log)


def sync_all(gql, settings, log):
    tags = composer_tags(gql, settings)
    if not tags:
        log("No composer tags (under the first parent of 'Fill in tags under') — nothing to do.")
        return {"scenes": 0}
    page, done, totals = 1, 0, {"performers_added": 0, "markers_tagged": 0, "markers_replaced": 0}
    while True:
        result = gql("""query($p: Int!) { findScenes(scene_filter: {has_markers: "true"}, filter: {per_page: 100, page: $p}) {
            count scenes { id } } }""", {"p": page})["findScenes"]
        for s in result["scenes"]:
            c = sync_scene(gql, settings, s["id"], log, tags)
            totals["performers_added"] += len(c.get("performers_added") or [])
            totals["markers_tagged"] += c.get("markers_tagged", 0)
            totals["markers_replaced"] += c.get("markers_replaced", 0)
            done += 1
        if page * 100 >= result["count"]:
            break
        page += 1
    log(f"Composers in step for {done} scenes: {totals['performers_added']} composer(s) added to scenes, "
        f"{totals['markers_tagged']} chapter(s) given the scene's composer, {totals['markers_replaced']} changed.")
    return {"scenes": done, **totals}
