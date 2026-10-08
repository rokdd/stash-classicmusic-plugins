"""How often and how long each chapter (marker) was played.

The page counts while the scene's video plays (see markers-as-chapters.js)
and sends it every half minute: seconds watched per chapter, and whether a
chapter now counts as played (once per visit: a minute of it, or half of a
shorter one). Kept in .chapter-plays.json in the plugin's folder:
{marker id: {"plays": n, "seconds": total, "last": "YYYY-MM-DDTHH:MM:SS"}}.
"""

import datetime
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, ".chapter-plays.json")
_lock = threading.Lock()


def load():
    try:
        with open(RECORD, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def add(plays):
    """plays: {marker id: {"seconds": s, "play": true/false}}."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with _lock:
        data = load()
        for mid, p in (plays or {}).items():
            entry = data.setdefault(str(mid), {"plays": 0, "seconds": 0, "last": None})
            entry["seconds"] = round(entry["seconds"] + max(0.0, float(p.get("seconds") or 0)), 1)
            if p.get("play"):
                entry["plays"] += 1
            if p.get("seconds") or p.get("play"):
                entry["last"] = now
        tmp = RECORD + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, RECORD)
    return {"saved": len(plays or {})}


def stats(gql, scene_id):
    markers = (gql("query($id: ID!) { findScene(id: $id) { scene_markers { id } } }", {"id": scene_id}).get("findScene")
               or {}).get("scene_markers") or []
    data = load()
    return {str(m["id"]): data[str(m["id"])] for m in markers if str(m["id"]) in data}
