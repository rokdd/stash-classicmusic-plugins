# Sidecar / local files (Stash scene scraper)

Fills in a scene from the files lying next to its video — nothing online.

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **Sidecar / local files** and **Install**. Needs Python 3 on the
server, no extra modules.

## Use

On a scene: **Edit → Scrape with… → Sidecar / local files**.

Stash tells a scraper only the scene, not its file, so the scraper asks
Stash for the video's path itself — at `http://localhost:9999`. If Stash
runs elsewhere or has a login, set `STASH_URL` (and `STASH_API_KEY`) in the
environment Stash runs in.

## What it reads

| File next to the video | Fills in |
|---|---|
| medici.tv's JSON — `<video>.json`, `<video>.medici.json`, or any medici.tv JSON in the folder if it's the only one or its name matches the video's | title (with the festival), description, date, cast and composers as performers, director, festival and venue as tags |
| A Kodi / Jellyfin NFO — `<video>.nfo`, else `movie.nfo` / `musicvideo.nfo` | title, plot, date, studio, director, actors (and artist, composer) as performers, genres and tags |
| a **VDR** recording — `<Title>/<date.time….rec>/001.vdr` or `00001.ts` | from VDR's programme guide entry beside it (`info` / `info.vdr`): title and subtitle, description, broadcast start, channel as studio; without it, the folder names: the title and the broadcast date |
| yt-dlp's info file — `<video>.info.json` | title, description, date, the channel as studio, the page's URL, tags |
| A cover — `<video>.jpg` / `.png` / `-poster.jpg` / `-thumb.jpg` / `-fanart.jpg`, or `poster` / `folder` / `cover` / `thumb` in the folder | the scene's cover |

When there are several: medici.tv first, then the NFO, then VDR's, then yt-dlp's file —
field by field; performers, tags and URLs come from all of them, and the
scene's own URLs stay.

Chapters in those files (medici.tv's, yt-dlp's) are offered by
[Markers as Chapters](../../plugins/markers-as-chapters/): when the scene has
no markers yet, saving it after the scrape brings up a note at the bottom
right asking whether to import them as markers (shown first in a dialog;
nothing is saved until you create them).
