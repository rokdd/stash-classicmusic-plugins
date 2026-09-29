# StashDB Tag Descriptions (Stash plugin)

Copies each tag's description from StashDB for every tag that has a
StashDB ID — and keeps it up to date.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/stashdb-tag-descriptions

## What it does

- **New or newly linked tags** get their description right away: when a
  tag is created, or its StashDB ID is set or changed, the plugin fetches
  that tag's description.
- **All tags** are refreshed every 7 days (adjustable), so changes on
  StashDB reach your tags too. Stash has no scheduler of its own, so this
  starts while Stash is open in a browser: 30 seconds after a page loads,
  if the last automatic refresh is older than the setting. It shows up in
  Settings → Tasks as "Update tag descriptions from StashDB (automatic)".
- **Any time by hand**: Settings → Tasks → **Update tag descriptions from
  StashDB**.

## Your own descriptions are kept

- An **empty** description is filled.
- A description **this plugin wrote** is updated when StashDB's changes.
- A description **you wrote or edited yourself** is left alone.

The plugin remembers what it wrote in `written-descriptions.json` in its
own folder; that's how it tells its text from yours. Turn on
**Overwrite descriptions you wrote yourself** to replace every
description with StashDB's instead.

## Settings

Settings → Plugins → StashDB Tag Descriptions:

| Setting | Effect |
|---|---|
| Refresh every … days | How often all tags are refreshed automatically. Empty = every 7 days; 0 = off (the task still works). |
| Overwrite descriptions you wrote yourself | Replace every description with StashDB's, not just empty ones and the plugin's own. |

## Requirements

- Your StashDB (or other stash-box) endpoint with its API key under
  Settings → Metadata Providers → Stash-box Endpoints. Any stash-box set
  up there works, not just StashDB.
- Tags with a StashDB ID — Stash v0.28 or newer can store StashDB IDs on
  tags; link them on the tag's edit page or through the tagger.
- Python 3 on the server — standard library only, nothing to install.
