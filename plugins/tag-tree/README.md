# Tag Tree (Stash plugin)

Shows all your tags as a collapsible tree of parents and children — the
hierarchy you set up with each tag's *Parent tags* / *Sub-tags* — on its
own page, and keeps tag descriptions up to date from StashDB (see
[StashDB descriptions](#stashdb-descriptions)).

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/tag-tree

## Opening it

Stash's own **Tags** page gets a **Cards | Tree** switch above its list:
**Tree** shows the tag tree in place of the cards, **Cards** brings back
Stash's usual view. Your choice is remembered in the browser. Other tag
lists — like the sub-tags on a tag's page — stay as they are.

Optionally, a **sitemap icon** button in Stash's top navigation bar opens
the Tags page straight in tree view — turn on Settings → Plugins → Tag Tree
→ **Show a tag tree button in the top bar** (off by default; reload the
page after changing it). The older address `/plugin/tag-tree` still shows
the tree as a page of its own.

Needs Stash v0.25 or newer (the plugin API that lets a plugin extend
Stash's pages).

## What it shows

- Every tag without a parent at the top level, its sub-tags nested
  beneath it, sorted by name.
- Each tag's image (if it has a custom one uploaded), its name — a link to
  its own tag page — how many scenes and markers use it, and its
  description (hover it to read all of it).
- A tag with several parents appears under each of them.
- A loop in the hierarchy (a tag that's its own ancestor) is shown once
  and marked "loop — already above" instead of repeating forever.

## Using it

- **Expand/collapse** a branch with the arrow in front of it, or all of
  them at once with **Expand all** / **Collapse all**. Which branches are
  open is remembered in your browser for next time.
- **Search** matches tag names and aliases. Matching tags are shown in
  their place in the tree, with the path from the top down to each one
  opened automatically.

## StashDB descriptions

For every tag with a StashDB ID, Tag Tree also copies the tag's description
from StashDB — and keeps it up to date.

### What it does

- **New or newly linked tags** get their description right away: when a
  tag is created, or its StashDB ID is set or changed, the plugin fetches
  that tag's description.
- **All tags** are refreshed every 7 days (adjustable), so changes on
  StashDB reach your tags too. Stash has no scheduler of its own, so this
  starts while Stash is open in a browser: 30 seconds after a page loads,
  if the last automatic refresh is older than the setting. It shows up in
  Settings → Tasks as "Update tag descriptions from StashDB (automatic)".
- **Any time by hand**: the **Update descriptions from StashDB** button on
  the tag tree page (or Settings → Tasks → **Update tag descriptions from
  StashDB**), or the **↻ StashDB** link next to a single tag. The tree
  reloads by itself once the update is done.

### Your own descriptions are kept

- An **empty** description is filled.
- A description **this plugin wrote** is updated when StashDB's changes.
- A description **you wrote or edited yourself** is left alone.

The plugin remembers what it wrote in `written-descriptions.json` in its
own folder; that's how it tells its text from yours. Turn on
**Overwrite descriptions you wrote yourself** to replace every
description with StashDB's instead.

### Settings

Settings → Plugins → Tag Tree:

| Setting | Effect |
|---|---|
| Show a tag tree button in the top bar | Adds the navigation bar button that opens the tree. Off by default. |
| Refresh every … days | How often all tags are refreshed automatically. Empty = every 7 days; 0 = off (the task still works). |
| Overwrite descriptions you wrote yourself | Replace every description with StashDB's, not just empty ones and the plugin's own. |

### Requirements

- Your StashDB (or other stash-box) endpoint with its API key under
  Settings → Metadata Providers → Stash-box Endpoints. Any stash-box set
  up there works, not just StashDB.
- Tags with a StashDB ID — Stash v0.28 or newer can store StashDB IDs on
  tags; link them on the tag's edit page or through the tagger.
- Python 3 on the server — standard library only, nothing to install.

### Coming from the separate "StashDB Tag Descriptions" plugin

That plugin is now part of Tag Tree. Uninstall it (Settings → Plugins),
or its hooks run alongside Tag Tree's. Your settings there need setting
again under Tag Tree; the record of which descriptions it wrote is picked
up automatically from its old folder, so your own texts stay protected.
