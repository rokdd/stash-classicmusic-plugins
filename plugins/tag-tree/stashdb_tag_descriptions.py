#!/usr/bin/env python3
"""
StashDB tag descriptions — the backend of the Tag Tree plugin.

Copies each tag's description from StashDB (or any other stash-box set up
under Settings > Metadata Providers) for tags that have a StashDB ID:

  - task "Update tag descriptions from StashDB": every tag at once;
  - hooks on tag create/update: just that tag, right away, so a tag
    imported or linked to StashDB gets its description immediately;
  - stashdb-auto-refresh.js starts the task by itself every few days when
    Stash is open in a browser (Stash has no scheduler of its own);
  - the tag tree page's buttons: all tags, or one ("sync_tag").

Descriptions you wrote yourself are never replaced, unless the "overwrite"
setting is on: a description is only written when the tag has none, or
when it's still exactly what this plugin wrote last time (kept in
written-descriptions.json next to this script).

Standard library only — nothing to pip install.
"""

import json
import os
import sys
import urllib.error
import urllib.request

# Stash's id for this plugin — the yml manifest's filename minus ".yml".
PLUGIN_ID = "tagTree"

# How many tags to ask stash-box for per request.
BATCH_SIZE = 50

# Tag id → the description this plugin last wrote to it. Lets a later run
# tell "still ours, safe to update" apart from "edited by hand, leave it".
WRITTEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "written-descriptions.json")

# Where the separate "StashDB Tag Descriptions" plugin kept that record
# before it became part of Tag Tree: its own folder, a sibling of this one
# (named by plugin id when installed from a plugin source, or by folder
# name when copied by hand). Read once if ours doesn't exist yet.
OLD_WRITTEN_FILES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), folder, "written-descriptions.json")
    for folder in ("stashdbTagDescriptions", "stashdb-tag-descriptions")
]


# ---------------------------------------------------------------------------
# Stash plugin log protocol: SOH, level letter, STX, message.
# ---------------------------------------------------------------------------

def _log(level, message):
    sys.stderr.write(f"\x01{level}\x02{message}\n")
    sys.stderr.flush()


def log_info(message):
    _log("i", message)


def log_warn(message):
    _log("w", message)


def log_progress(fraction):
    _log("p", f"{max(0.0, min(1.0, fraction)):.4f}")


def write_plugin_output(output=None, error=None):
    print(json.dumps({"error": str(error)} if error else {"output": output or "ok"}))


# ---------------------------------------------------------------------------
# GraphQL over HTTP (stdlib only)
# ---------------------------------------------------------------------------

def post_graphql(url, query, variables=None, headers=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # GraphQL servers explain a rejected query in the body — pass that
        # on instead of just the status code.
        detail = ""
        try:
            errors = json.loads(exc.read().decode("utf-8")).get("errors") or []
            detail = "; ".join(e.get("message", "") for e in errors)
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"HTTP {exc.code} from {url}" + (f": {detail}" if detail else "")) from exc
    if payload.get("errors"):
        raise RuntimeError(f"GraphQL error from {url}: {payload['errors']}")
    return payload["data"]


class Stash:
    def __init__(self, server_connection):
        scheme = server_connection.get("Scheme", "http")
        host = server_connection.get("Host") or "localhost"
        if host in ("0.0.0.0", ""):
            host = "localhost"
        port = server_connection.get("Port", 9999)
        self.url = f"{scheme}://{host}:{port}/graphql"
        self.headers = {}
        cookie = server_connection.get("SessionCookie") or {}
        if cookie.get("Name") and cookie.get("Value"):
            self.headers["Cookie"] = f"{cookie['Name']}={cookie['Value']}"
        api_key = server_connection.get("ApiKey") or os.environ.get("STASH_API_KEY")
        if api_key:
            self.headers["ApiKey"] = api_key

    def call(self, query, variables=None):
        return post_graphql(self.url, query, variables, self.headers)

    def stash_boxes(self):
        """Configured stash-box endpoints (StashDB etc.), by endpoint URL."""
        data = self.call("query { configuration { general { stashBoxes { endpoint api_key name } } } }")
        boxes = data["configuration"]["general"]["stashBoxes"] or []
        return {b["endpoint"]: b for b in boxes if b.get("endpoint")}

    def plugin_settings(self):
        try:
            data = self.call("query { configuration { plugins } }")
            return (data["configuration"].get("plugins") or {}).get(PLUGIN_ID) or {}
        except Exception as exc:  # noqa: BLE001
            log_warn(f"Couldn't read plugin settings, using defaults: {exc}")
            return {}

    def tags(self, tag_id=None):
        fields = "id name description stash_ids { endpoint stash_id }"
        if tag_id is not None:
            data = self.call(f"query($id: ID!) {{ findTag(id: $id) {{ {fields} }} }}", {"id": tag_id})
            return [data["findTag"]] if data.get("findTag") else []
        data = self.call(f"query {{ findTags(filter: {{ per_page: -1 }}) {{ tags {{ {fields} }} }} }}")
        return data["findTags"]["tags"]

    def set_description(self, tag_id, description):
        self.call(
            "mutation($input: TagUpdateInput!) { tagUpdate(input: $input) { id } }",
            {"input": {"id": tag_id, "description": description}},
        )


def fetch_remote_tags(box, ids):
    """
    stash-box tags by id → {id: tag}, BATCH_SIZE per request. StashDB has
    no "several tags by id" query (newer stash-box code does, but StashDB
    doesn't run it), so each request asks for findTag once per tag, under
    its own alias: t0: findTag(id: $id0) …, t1: findTag(id: $id1) ….
    """
    found = {}
    headers = {"ApiKey": box["api_key"]} if box.get("api_key") else {}
    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start:start + BATCH_SIZE]
        params = ", ".join(f"$id{i}: ID!" for i in range(len(batch)))
        fields = " ".join(
            f"t{i}: findTag(id: $id{i}) {{ id name description deleted }}" for i in range(len(batch))
        )
        data = post_graphql(
            box["endpoint"],
            f"query({params}) {{ {fields} }}",
            {f"id{i}": stash_id for i, stash_id in enumerate(batch)},
            headers,
        )
        for tag in (data or {}).values():
            if tag:
                found[tag["id"]] = tag
    return found


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def load_written():
    for path in [WRITTEN_FILE] + OLD_WRITTEN_FILES:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return {}


def save_written(written):
    try:
        with open(WRITTEN_FILE, "w") as f:
            json.dump(written, f, indent=1, sort_keys=True)
        return True
    except OSError as exc:
        log_warn(
            f"Couldn't save {WRITTEN_FILE} ({exc}). Descriptions were still updated, but next time "
            f"only empty ones get filled, since the plugin can't tell its own text apart."
        )
        return False


def sync(stash, tag_id=None, quiet=False):
    """
    Updates descriptions for every tag (or just `tag_id`) that has a stash
    ID on a configured stash-box. Returns a one-line summary.
    """
    settings = stash.plugin_settings()
    overwrite = settings.get("overwrite") is True
    boxes = stash.stash_boxes()
    if not boxes:
        return "No stash-box (e.g. StashDB) is set up under Settings > Metadata Providers — nothing to fetch from."

    # Each tag's first stash ID on a configured endpoint.
    by_endpoint = {}
    for tag in stash.tags(tag_id):
        for sid in tag.get("stash_ids") or []:
            if sid.get("endpoint") in boxes and sid.get("stash_id"):
                by_endpoint.setdefault(sid["endpoint"], []).append((tag, sid["stash_id"]))
                break
    total = sum(len(v) for v in by_endpoint.values())
    if not total:
        return "No tags with a StashDB ID." if tag_id is None else "Tag has no StashDB ID on a configured stash-box."

    written = load_written()
    updated, unchanged, own_text, missing = 0, 0, 0, 0
    done = 0
    for endpoint, items in by_endpoint.items():
        box = boxes[endpoint]
        if not quiet:
            log_info(f"Fetching {len(items)} tag(s) from {box.get('name') or endpoint}...")
        remote = fetch_remote_tags(box, [stash_id for _, stash_id in items])
        for tag, stash_id in items:
            done += 1
            if not quiet:
                log_progress(done / total)
            remote_tag = remote.get(stash_id)
            description = ((remote_tag or {}).get("description") or "").strip()
            if not remote_tag or remote_tag.get("deleted") or not description:
                missing += 1
                continue
            current = (tag.get("description") or "").strip()
            key = str(tag["id"])
            if current == description:
                written[key] = description
                unchanged += 1
                continue
            # Only replace a description that's empty or still the one this
            # plugin wrote last time — never one written by hand.
            if overwrite or not current or written.get(key) == current:
                stash.set_description(tag["id"], description)
                written[key] = description
                updated += 1
                if tag_id is not None or not quiet:
                    log_info(f"Updated description of \"{tag['name']}\"")
            else:
                own_text += 1
    save_written(written)

    parts = [f"Updated {updated}", f"already up to date {unchanged}"]
    if own_text:
        parts.append(f"kept your own text on {own_text} (turn on \"Overwrite\" to replace it)")
    if missing:
        parts.append(f"no description on StashDB for {missing}")
    return "Tag descriptions: " + ", ".join(parts) + "."


def main():
    raw = sys.stdin.read()
    plugin_input = json.loads(raw) if raw.strip() else {}
    args = plugin_input.get("args") or {}
    stash = Stash(plugin_input.get("server_connection") or {})

    if args.get("mode") == "sync_tag" and args.get("tag_id"):
        # One tag, from its button in the tag tree.
        try:
            summary = sync(stash, tag_id=args["tag_id"])
        except Exception as exc:  # noqa: BLE001
            write_plugin_output(error=f"Updating the tag's description failed: {exc}")
            return
        log_info(summary)
        write_plugin_output(output=summary)
        return

    hook = args.get("hookContext")
    if hook and hook.get("type") == "Tag.Update.Post" and "stash_ids" not in (hook.get("inputFields") or []):
        # Only an update that sets or changes the tag's StashDB ID matters.
        # This also skips the updates this plugin makes itself — otherwise
        # a full sync would fire this hook once per description it writes.
        write_plugin_output(output="Tag update didn't touch its StashDB ID — nothing to do.")
        return
    try:
        if hook:
            # A new tag, or one just linked to StashDB: just that one, quietly.
            summary = sync(stash, tag_id=hook.get("id"), quiet=True)
        else:
            summary = sync(stash)
    except Exception as exc:  # noqa: BLE001
        write_plugin_output(error=f"Updating tag descriptions failed: {exc}")
        return
    log_info(summary)
    write_plugin_output(output=summary)


if __name__ == "__main__":
    main()
