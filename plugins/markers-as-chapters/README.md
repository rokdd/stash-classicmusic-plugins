# Markers as Chapters (Stash plugin)

Imports a scene's chapters as markers — from the video file, a file next
to it, YouTube, ARTE Concert, a pasted tracklist or programme, or the
pauses between movements in the audio. Made for concert recordings: one
marker per work or movement.

## Install

Add the plugin source `https://rokdd.github.io/stash-classicmusic-plugins/main/index.yml`
under Settings → Plugins → Available Plugins, and install **Markers as
Chapters**. It needs Python 3 on the server (no extra modules); the online
chapters scraper also needs **yt-dlp** (`sudo apt install yt-dlp`).

Works together with [Marker Improvements](../marker-improvements-plugin/)
(the new markers show up right away in its list and on the seek bar), but
doesn't need it.

## Scraping markers

Stash scrapes scenes, galleries and performers, but not markers. This
plugin adds marker scrapers that work the same way: a **Scrape markers…**
button next to **Create Marker** in the Markers tab lists

- every scraper that scrapes the scene itself,
- one entry per scene URL a URL scraper handles, and **other URL…** to
  enter one,
- every scraper that reads text (**… paste text or pick a file**).

The markers found open in a dialog: tick the ones to create, change
titles, primary tag and tags, and **shift all times** (when the online
video has a longer or shorter intro than your file). Markers already in
the scene at that time are flagged and not ticked. **Create markers**
adds them, and the page updates.

Built in:

- **Video file chapters** — chapters stored in the file (MKV, MP4 …), read
  with Stash's ffprobe.
- **Online chapters (yt-dlp)** — the chapters of the video online (YouTube
  chapters, e.g. a concert's movements), from the scene's URLs or one you
  enter. Needs yt-dlp on the server (the **Path to yt-dlp** setting, else
  Scene Improvements' one, else the PATH).
- **arte.tv / ARTE Concert** — the chapters of an arte.tv video (ARTE
  Concert videos are arte.tv videos too), from the scene's arte.tv URL or
  one you enter: ARTE Concert splits a concert into its works
  (e.g. "Sergej Rachmaninow - Konzert für Klavier und Orchester Nr. 3").
  Titles come in the URL's language (/de/, /fr/ …). Composer and
  orchestra named in a title ("Orchestra : Composer - Work", "Composer,
  Work") are suggested as tags — used when you have a tag of that name or
  alias. Some videos have no chapters at arte; then nothing is found (the
  **Pauses between movements** with the program from the description
  helps). Each chapter ends where the next starts, the last at the end of
  the video. Needs nothing extra (reads arte's player API).
- **Plain text** — paste text or pick a file (it's read in your browser,
  so from the device you're on), check and edit it, then **Scrape**. Every
  line with a time in it becomes a marker, the rest of the line its title;
  lines without a time are skipped. Times like `1:23`, `1:02:03`,
  `[12:34]`, `(5:10)`, `3m20s`; a range like `1:23 - 4:56` gives the end
  too, otherwise a marker ends where the next starts (the last at the end
  of the video). A **CUE sheet** works too: one marker per track, its
  PERFORMER as a tag. **Titles only** — no line has a time: the lines are
  taken as the pieces in order and placed at the pauses in the audio, as
  **Pauses between movements** does; the dialog then says how many pauses
  were found, and which titles got no marker if there were too few.
- **Chapter file next to the video** — a file with the video's name next
  to it on the server: `Concert.cue`, `Concert.chapters.txt` (OGM
  chapters or a tracklist), `Concert.chapters.xml` (Matroska chapters, as
  from mkvextract), `Concert.ffmetadata`, `Concert.info.json` (yt-dlp) or
  `Concert.txt` (a tracklist) — also with the video's extension in the
  name (`Concert.mp4.cue`).
- **Pauses between movements** — finds the pauses in the scene's own
  audio (ffmpeg, a few seconds to a minute for a concert) and puts a
  marker where the music starts again, ending where the next pause
  begins. How quiet counts as a pause follows the recording, so the
  audience's quiet between movements counts. Two ways:
  - **Pauses between movements**: every pause gives a marker ("Part 1",
    "Part 2" …).
  - **Pauses between movements — paste text or pick a file…**: paste the
    titles of the movements or works in order, one per line — e.g. the
    programme from ARD, BBC or the concert hall's site, which list the
    pieces but no times. It looks for exactly that many pieces (the
    longest pauses split them; if there are too few pauses, shorter ones
    count too) and names them. Times at the start of a line are ignored.

  Applause between works can hide a pause; check the result in the
  dialog and shift or untick markers there.

**Primary tag**: every marker needs one. A scraper can name it per marker;
otherwise the **Primary tag for scraped markers** setting is used (empty:
`Chapter`), and you can change it in the dialog. A primary tag that
doesn't exist yet is created. Other tags are matched by name or alias;
ones that don't exist are left out (and listed).

## Composers and other tags from the titles

Every scraper's markers get tags filled in from their titles: tags below
the **Fill in tags under** parent tags (default `Composers` — the composer
tags [Tag Improvements](../tag-improvements/) keeps for performers marked
as composers) are found by

- their whole name or an alias, as whole words, or
- just the surname: "Beethoven: Symphony No. 5" → *Ludwig van Beethoven*.
  Only when one tag has that surname — two Bachs: neither, unless the
  title has more of the name. Spellings that differ only at the end count
  too (*Rachmaninow* / *Rachmaninoff*, *Mussorgski* / *Mussorgsky*); for
  others give the tag an alias.

Upper/lower case and accents (Dvořák / Dvorak) don't matter. A name the
scraper suggests (ARTE Concert's composers) is replaced by the matching
tag. The review dialog says how many markers got tags this way; change
them there as needed.

## Your own marker scrapers

Put them in a folder on the server and enter it as **Marker scrapers
folder**. A scraper is a `.yaml` file in Stash's scraper format, with
`markerByFragment` (scrape the scene), `markerByURL` (scrape a URL) and/or
`markerByText` (read pasted text or a file):

```yaml
name: My concert site
markerByFragment:
  action: script
  script:
    - python
    - my_scraper.py
markerByURL:
  - action: script
    url:
      - concerts.example.com
    script:
      - python
      - my_scraper.py
markerByText:
  action: script
  script:
    - python
    - my_scraper.py
```

The script runs in the scraper's folder. It gets JSON on stdin —
`{"scene": {id, title, code, details, date, urls, files: [{path,
duration}], scene_markers: [...]}}`, plus `"url"` when scraping a URL or
`"text"` when reading text — and
prints a JSON list of markers:

```json
[{"seconds": 0, "end_seconds": 512.4, "title": "I. Allegro con brio",
  "primary_tag": "Movement", "tags": ["Beethoven"]}]
```

Only `seconds` is required. The environment variables `STASH_FFPROBE` and
`STASH_YTDLP` name the ffprobe and yt-dlp to use. Only `action: script`
is supported. Use `.yaml` (not `.yml`) for scrapers inside Stash's plugins
folder — Stash takes every `.yml` there for a plugin.

## Settings

- **Primary tag for scraped markers** — the primary tag for imported
  markers when the scraper doesn't name one (empty: `Chapter`).
- **Marker scrapers folder** — a folder with your own scrapers (above).
- **Path to yt-dlp** — for the online chapters; empty: Scene
  Improvements' setting, else yt-dlp on the PATH.
- **Fill in tags under** — parent tags whose tags are filled in from the
  titles (above); empty: `Composers`, `-` switches it off.

These were Marker Improvements' settings before this became a plugin of
its own; values set there are still used until you set them here.
