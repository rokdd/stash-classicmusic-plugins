"""
Composer tags — part of the Tag Improvements plugin.

Markers can only carry tags, not performers. So every performer marked as
a composer (the custom field in the "Composer field" setting, default
"composer", set to anything but no/false/0) gets a tag of their own, kept
in step with the performer:

  - same name (with the performer's disambiguation in brackets if another
    composer tag already has that name);
  - the performer's aliases as aliases (ones another tag already uses are
    left out — Stash allows each name only once);
  - the performer's image;
  - the performer's details as description — unless you wrote the tag's
    description yourself;
  - under the parent tag in the "Composer parent tag" setting (default
    "Composers", created if needed); other parents the tag has stay.

The tag remembers its performer in its custom field "performer_id", so a
renamed performer renames its tag (the old name stays as an alias). An
existing tag with the performer's name is taken over instead of creating
a second one. Tags are never deleted: a performer no longer marked as
composer keeps the tag.

Runs for a performer when it's created or saved (hook), and for every
performer with the task "Sync composer tags". Standard library only.
"""

import base64
import hashlib
import re
import urllib.request

DEFAULT_FIELD = "composer"
DEFAULT_PARENT = "Composers"
NO = {"", "no", "false", "0", "nein", "non", "off"}

PERFORMER_FIELDS = "id name disambiguation alias_list details image_path custom_fields"
TAG_FIELDS = "id name aliases description custom_fields parents { id }"


def settings_of(settings):
    field = (settings.get("composerField") or "").strip() or DEFAULT_FIELD
    parent = (settings.get("composerParentTag") or "").strip() or DEFAULT_PARENT
    return field, parent


def is_composer(performer, field):
    fields = performer.get("custom_fields") or {}
    lowered = {k.lower(): v for k, v in fields.items()}
    if field.lower() not in lowered:
        return False
    return str(lowered[field.lower()]).strip().lower() not in NO


def sha1(data):
    return hashlib.sha1(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def has_image(performer):
    path = performer.get("image_path") or ""
    return bool(path) and not re.search(r"[?&]default=true\b", path)


class ComposerSync:
    def __init__(self, stash, settings, log):
        self.stash = stash
        self.field, self.parent_name = settings_of(settings)
        self.log = log
        self.tags = stash.call(f"query {{ findTags(filter: {{ per_page: -1 }}) {{ tags {{ {TAG_FIELDS} }} }} }}")["findTags"]["tags"]
        self.parent_id = None

    # -- tag lookups -------------------------------------------------------

    def tag_for(self, performer):
        pid = str(performer["id"])
        for t in self.tags:
            if str((t.get("custom_fields") or {}).get("performer_id") or "") == pid:
                return t
        names = {performer["name"].strip().lower()}
        for t in self.tags:
            if (t.get("custom_fields") or {}).get("performer_id"):
                continue  # another performer's tag
            if t["name"].strip().lower() in names:
                return t
        return None

    def used_names(self, except_id=None):
        """Every tag name and alias in use, by other tags."""
        used = set()
        for t in self.tags:
            if except_id is not None and str(t["id"]) == str(except_id):
                continue
            used.add(t["name"].strip().lower())
            used.update(a.strip().lower() for a in t.get("aliases") or [])
        return used

    def ensure_parent(self):
        if self.parent_id:
            return self.parent_id
        for t in self.tags:
            if t["name"].strip().lower() == self.parent_name.lower():
                self.parent_id = str(t["id"])
                return self.parent_id
        created = self.stash.call(
            "mutation($input: TagCreateInput!) { tagCreate(input: $input) { id } }",
            {"input": {"name": self.parent_name}},
        )["tagCreate"]
        self.parent_id = str(created["id"])
        self.tags.append({"id": self.parent_id, "name": self.parent_name, "aliases": [], "description": "",
                          "custom_fields": {}, "parents": []})
        self.log(f"Created the tag {self.parent_name}.")
        return self.parent_id

    def image_data(self, performer):
        """(data URL, hash) of the performer's image, or (None, None)."""
        if not has_image(performer):
            return None, None
        url = performer["image_path"]
        request = urllib.request.Request(url, headers=self.stash.headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
            kind = response.headers.get_content_type() or "image/jpeg"
        return f"data:{kind};base64,{base64.b64encode(data).decode()}", sha1(data)

    # -- one performer ------------------------------------------------------

    def sync(self, performer):
        """Creates or updates the performer's tag. Returns a short note, or
        None when there was nothing to do."""
        if not is_composer(performer, self.field):
            return None
        tag = self.tag_for(performer)
        parent_id = self.ensure_parent()
        used = self.used_names(except_id=tag["id"] if tag else None)

        name = performer["name"].strip()
        if name.lower() in used and performer.get("disambiguation"):
            name = f"{name} ({performer['disambiguation'].strip()})"
        if name.lower() in used:
            if not tag:
                self.log(f"{performer['name']}: another tag is already called {name} — not created.")
                return None
            name = tag["name"]  # keep the tag's name rather than clash

        aliases = []
        # A renamed performer's old name stays findable, as an alias.
        old_name = [tag["name"]] if tag and tag["name"] != name else []
        for a in [*(tag.get("aliases") if tag else []), *old_name, *(performer.get("alias_list") or [])]:
            a = a.strip()
            if a and a.lower() != name.lower() and a.lower() not in used and a.lower() not in [x.lower() for x in aliases]:
                aliases.append(a)

        fields = dict(tag.get("custom_fields") or {}) if tag else {}
        update = {"name": name, "aliases": aliases}
        parents = {str(p["id"]) for p in (tag.get("parents") if tag else [])}
        if parent_id not in parents:
            update["parent_ids"] = sorted(parents | {parent_id})

        details = (performer.get("details") or "").strip()
        current = (tag.get("description") or "").strip() if tag else ""
        written = fields.get("performer_details_sha1")
        if details and (not current or (written and sha1(current) == written)) and current != details:
            update["description"] = details
        new_fields = {"performer_id": str(performer["id"])}
        if details and update.get("description", current) == details:
            new_fields["performer_details_sha1"] = sha1(details)

        image, image_hash = None, None
        try:
            image, image_hash = self.image_data(performer)
        except Exception as exc:  # noqa: BLE001
            self.log(f"{performer['name']}: couldn't read the image ({exc}).")
        if image and image_hash != fields.get("performer_image_sha1"):
            update["image"] = image
            new_fields["performer_image_sha1"] = image_hash

        if tag:
            changes = {k: v for k, v in update.items()
                       if k in ("image", "description", "parent_ids")
                       or (k == "name" and v != tag["name"])
                       or (k == "aliases" and sorted(v) != sorted(tag.get("aliases") or []))}
            changed_fields = {k: v for k, v in new_fields.items() if fields.get(k) != v}
            if not changes and not changed_fields:
                return None
            payload = {"id": tag["id"], **changes}
            if changed_fields:
                payload["custom_fields"] = {"partial": changed_fields}
            self.stash.call("mutation($input: TagUpdateInput!) { tagUpdate(input: $input) { id } }", {"input": payload})
            tag.update({k: v for k, v in changes.items() if k in ("name", "aliases", "description")})
            tag["custom_fields"] = {**fields, **changed_fields}
            return f"updated {name} ({', '.join(sorted(list(changes) + (['link'] if 'performer_id' in changed_fields else [])))})"

        payload = {**update, "custom_fields": new_fields}
        payload.setdefault("parent_ids", [parent_id])
        created = self.stash.call("mutation($input: TagCreateInput!) { tagCreate(input: $input) { id } }", {"input": payload})["tagCreate"]
        self.tags.append({"id": str(created["id"]), "name": name, "aliases": aliases,
                          "description": update.get("description", ""), "custom_fields": new_fields,
                          "parents": [{"id": p} for p in payload["parent_ids"]]})
        return f"created {name}"


def performers(stash, performer_id=None):
    if performer_id is not None:
        data = stash.call(f"query($id: ID!) {{ findPerformer(id: $id) {{ {PERFORMER_FIELDS} }} }}", {"id": performer_id})
        return [data["findPerformer"]] if data.get("findPerformer") else []
    data = stash.call(f"query {{ findPerformers(filter: {{ per_page: -1 }}) {{ performers {{ {PERFORMER_FIELDS} }} }} }}")
    return data["findPerformers"]["performers"]


def run(stash, settings, log, log_progress=None, performer_id=None):
    """Syncs one performer (performer_id) or all. Returns a summary."""
    field, _parent = settings_of(settings)
    found = performers(stash, performer_id)
    composers = [p for p in found if is_composer(p, field)]
    if not composers:
        return None if performer_id is not None else f"Composer tags: no performer has the custom field \"{field}\"."
    sync = ComposerSync(stash, settings, log)
    notes = []
    for i, p in enumerate(composers):
        try:
            note = sync.sync(p)
        except Exception as exc:  # noqa: BLE001
            note = f"{p['name']}: failed ({exc})"
        if note:
            notes.append(note)
        if log_progress:
            log_progress((i + 1) / len(composers))
    if performer_id is not None:
        return f"Composer tag: {notes[0]}." if notes else None
    return (f"Composer tags: {len(composers)} composers, " +
            (f"{len(notes)} changed — " + "; ".join(notes[:30]) + ("…" if len(notes) > 30 else "") if notes else "all up to date") + ".")
