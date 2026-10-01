"""
Task history — part of the Advanced File Operations plugin.

Stash keeps no history of finished tasks: its task list only shows what's
queued or running, and keeps just the last 10 finished ones for lookups.
The browser side (task-history.js) notices every task that finishes while
a Stash page is open, and hands it here to be kept — in
task-history.json next to this script, so every browser and device sees
the same history. Runs through Stash's runPluginOperation:

  - history_add:   args "entries" — a JSON list of finished tasks
  - history_list:  returns the history, newest first, and the highest
                   task id seen (so a page can look for ones it missed)
  - history_remove: args "key" ("<id>|<addTime>") — removes one entry
  - history_clear: empties it

Tasks matching the "Task history: ignore" setting aren't kept, and ones
kept before the rule was added are left out of the list.

Entries are kept once each — by task id and the time it was added, since
Stash numbers tasks from 1 again after a restart — and only the newest
MAX_ENTRIES are kept. Standard library only.
"""

import json
import os
import re
import tempfile

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task-history.json")
MAX_ENTRIES = 500
FIELDS = ("id", "description", "status", "addTime", "startTime", "endTime", "error")


def _load():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data):
    # Written to a temporary file first and then moved into place, so two
    # pages saving at the same moment can't leave a half-written file.
    folder = os.path.dirname(HISTORY_FILE)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".task-history-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)


def ignore_rules(settings):
    """The "Task history: ignore" setting as matchers. Comma- or line-
    separated; upper/lower case ignored. Without a * a rule matches any task
    whose description contains it; with a * it's a pattern for the whole
    description (* = any text), e.g. "Scan*" or "*(automatic)"."""
    rules = []
    for raw in re.split(r"[,\n]", (settings or {}).get("historyIgnore") or ""):
        rule = raw.strip().lower()
        if not rule:
            continue
        if "*" in rule:
            pattern = re.compile("^" + ".*".join(re.escape(p) for p in rule.split("*")) + "$")
            rules.append(lambda d, p=pattern: bool(p.match(d)))
        else:
            rules.append(lambda d, r=rule: r in d)
    return rules


def ignored(entry, rules):
    description = (entry.get("description") or "").lower()
    return any(rule(description) for rule in rules)


def _key(entry):
    return f"{entry.get('id')}|{entry.get('addTime')}"


def _sort_time(entry):
    return entry.get("endTime") or entry.get("startTime") or entry.get("addTime") or ""


def add(entries, rules=()):
    data = _load()
    history = data.get("entries") or []
    known = {_key(e) for e in history}
    added = 0
    for raw in entries or []:
        entry = {k: raw.get(k) for k in FIELDS}
        if entry["id"] is None or _key(entry) in known or ignored(entry, rules):
            continue
        known.add(_key(entry))
        history.append(entry)
        added += 1
    history.sort(key=_sort_time, reverse=True)
    data["entries"] = history[:MAX_ENTRIES]
    ids = [int(e["id"]) for e in data["entries"] if str(e.get("id", "")).isdigit()]
    data["last_id"] = max(ids + [int(data.get("last_id") or 0)]) if ids else data.get("last_id", 0)
    if added:
        _save(data)
    return {"added": added, "total": len(data["entries"])}


def run(args, settings=None):
    mode = args.get("mode")
    rules = ignore_rules(settings)
    if mode == "history_add":
        return add(json.loads(args.get("entries") or "[]"), rules)
    if mode == "history_list":
        data = _load()
        entries = [e for e in data.get("entries") or [] if not ignored(e, rules)]
        return {"entries": entries, "last_id": data.get("last_id") or 0}
    if mode == "history_remove":
        data = _load()
        key = args.get("key")
        before = len(data.get("entries") or [])
        data["entries"] = [e for e in data.get("entries") or [] if _key(e) != key]
        if len(data["entries"]) != before:
            _save(data)
        return {"removed": before - len(data["entries"])}
    if mode == "history_clear":
        _save({"entries": [], "last_id": _load().get("last_id") or 0})
        return {"cleared": True}
    raise ValueError(f"Unknown task history mode: {mode}")
