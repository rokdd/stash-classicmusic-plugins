# Tag Improvements (Stash plugin)

Tag tools for Stash, in one plugin (formerly called **Tag Tree**):

- **[Tag tree](#opening-it)** — all your tags as a collapsible tree of
  parents and children, as a view on Stash's own Tags page.
- **[StashDB descriptions](#stashdb-descriptions)** — tag descriptions
  copied from StashDB and kept up to date.
- **[Better tag search](#better-tag-search)** — every word, in any order,
  in name, aliases, description and parent tags — in every tag field.
- **[Merging tags when scraping](#merging-tags-when-scraping-a-scene)** —
  scraping a scene adds the scraped tags to the existing ones instead of
  replacing them.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/tag-improvements

## Opening it

Stash's own **Tags** page gets a **Cards | Tree** switch above its list:
**Tree** shows the tag tree in place of the cards, **Cards** brings back
Stash's usual view. Your choice is remembered in the browser. Other tag
lists — like the sub-tags on a tag's page — stay as they are.

Optionally, a **sitemap icon** button in Stash's top navigation bar opens
the Tags page straight in tree view — turn on Settings → Plugins → Tag Improvements
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

## Better tag search

Every tag field in Stash — on a scene's Edit tab, in the marker form, for
performers, in filters — finds tags more easily:

- **Every word you type, in any order**: `symph beet` finds
  "Beethoven: Symphony No. 5".
- **Not just the name**: a word can match the tag's name, its aliases, its
  **description** or the names of the tags **above it** — so `strings`
  finds Violin and Viola if they're sub-tags of Strings.
- Tags whose name matches come first.

The search runs in the browser, over the whole tag list (loaded once and
again whenever tags change). Turn it off with **Use Stash's plain tag
search** to get Stash's own (name and aliases, as typed).

### Large tag dropdown

Every tag dropdown shows each tag's **parent tags** after its name, greyed
out: "Solo (Violin)".

At its top is a switch: **⤢ Larger, with images**. Then the dropdown
becomes a panel the whole height of the window, in front of the page,
with what you've typed at its top; it shows each tag's **image** and
**description**, and closes as soon as you've picked a tag; **⤡ Smaller**
switches back. Your browser remembers the choice for all tag
dropdowns; the **Large tag dropdown** setting is how they start.

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

Settings → Plugins → Tag Improvements:

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

## Composer tags

Markers can only carry tags, not performers. So every performer marked as
a composer gets a tag of their own, which markers can carry (and which
[Markers as Chapters](../markers-as-chapters/) fills in from chapter
titles):

1. Mark the performer: **Edit → Custom Fields**, field `composer`, value
   e.g. `yes` (anything but no / false / 0). The field name is the
   **Composer field** setting.
2. On save, the performer's tag is created or updated, under the parent
   tag **Composers** (the **Composer parent tag** setting; created if
   needed):
   - the performer's **name** — with the disambiguation in brackets if
     another tag already has the name;
   - their **aliases** (ones another tag already uses are left out — Stash
     allows each name only once);
   - their **image**;
   - their **details** as description — unless you wrote the tag's
     description yourself, which is kept.
3. **Settings → Tasks → Sync composer tags** does this for every composer
   at once — the first time, or after editing many performers.

The tag remembers its performer (custom field `performer_id`), so renaming
the performer renames the tag, and the old name stays as an alias. A tag
that already has the performer's name is taken over, not duplicated.
Nothing is ever deleted: a performer no longer marked as composer keeps
the tag.

## Merging tags when scraping a scene

When you scrape a scene from its **Edit** tab — **Scrape with…** a scraper
or StashDB — Stash normally *replaces* the scene's tags with the scraped
ones. With this plugin the scrape dialog offers the scene's **existing
tags plus the scraped ones** instead.

### What you see

In the scrape dialog's **Tags** row, the scraped (right) side lists:

1. the scene's current tags, then
2. the scraped tags that matched a tag you already have and aren't on the
   scene yet, and
3. scraped tags Stash couldn't match to one of your tags — with their
   usual create/link buttons.

Everything else about the dialog is Stash's own: you can remove tags on
the right before applying, or pick the left (existing) side to keep the
tags as they were. Other fields — title, date, performers, … — behave as
before.

The Tagger view isn't affected; it has its own merge setting.

### Settings

Settings → Plugins → Tag Improvements → **Replace tags instead (Stash's
default)**: turn on to get Stash's usual replace behaviour back.

### How it works

The scrape dialog gets its data from Stash's scrape queries
(`scrapeSingleScene`, `scrapeSceneURL`). The plugin watches the page's
requests and, for those answers only, adds the scene's current tags to
the scraped tag list before the dialog reads it — so no part of Stash's
own page is patched. Only on a scene's own page, and if anything goes
wrong it leaves Stash's answer untouched.

Scenes only for now; galleries and images scrape the same way and can
follow.

### Coming from the separate "Scrape Tag Merge" plugin

That plugin is now part of Tag Improvements. Uninstall it (Settings →
Plugins); its "Replace tags instead" setting, if you changed it, needs
setting again here.
