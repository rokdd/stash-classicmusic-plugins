# Markers as Chapters (Stash plugin)

Imports a scene's chapters as markers — from the video file, a file next
to it, YouTube, ARTE Concert, a pasted tracklist or programme, or the
pauses between movements in the audio, and checks every import against
those pauses. Made for concert recordings: one
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
  with Stash's ffprobe. Broken chapters are handled: titles like "nan",
  "Init" or the file's own name are left out; when every chapter starts at
  0:00, an MP4/M4V's chapter track is read directly (it may still have the
  times), with titles decoded properly ("schönen", not "sch�nen"). With no
  times anywhere, no markers are made — the dialog lists the titles to
  paste into **Plain text**, which places them at the pauses.
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
  alias. Some videos have no chapters at arte; then nothing is found
  (paste the programme from the description into **Plain text** — titles
  only are placed at the pauses). Each chapter ends where the next starts, the last at the end of
  the video. Needs nothing extra (reads arte's player API).
- **ORF ON** — the segments of an ORF ON video (on.orf.at, also old
  tvthek.orf.at links), from the scene's ORF URL or one you enter. ORF
  splits a broadcast into segments with titles — a concert usually into
  its pieces; each segment starts where the one before it ends (their
  exact lengths add up to the whole video). ORF ON keeps videos only for a
  while — after that there's nothing to read, and the dialog says so.
- **Plain text** — paste text or pick a file (it's read in your browser,
  so from the device you're on), check and edit it, then **Scrape**. Every
  line with a time in it becomes a marker, the rest of the line its title;
  lines without a time are skipped. Times like `1:23`, `1:02:03`,
  `[12:34]`, `(5:10)`, `3m20s`; a range like `1:23 - 4:56` gives the end
  too, otherwise a marker ends where the next starts (the last at the end
  of the video). A **CUE sheet** works too: one marker per track, its
  PERFORMER as a tag.

  **Titles only** — no line has a time: the lines are taken as the pieces
  in order, e.g. the programme from ARD, BBC or the concert hall's site,
  which list the pieces but no times. The video is split at the longest
  pauses in its audio into exactly that many pieces, named in order (with
  too few pauses, shorter ones count too); the dialog says how many pauses
  were found, and which titles got no marker if there were too few.
- **Chapter file next to the video** — a file with the video's name next
  to it on the server: `Concert.cue`, `Concert.chapters.txt` (OGM
  chapters or a tracklist), `Concert.chapters.xml` (Matroska chapters, as
  from mkvextract), `Concert.ffmetadata`, `Concert.info.json` (yt-dlp) or
  `Concert.txt` (a tracklist) — also with the video's extension in the
  name (`Concert.mp4.cue`).

### Checked against the audio

Whatever the scraper, the review dialog also checks the markers against
the **pauses in the scene's own audio** — where pieces and movements
usually start. The pauses are found with ffmpeg (a few seconds to a
minute for a concert, the first time; it's remembered per file, so
scraping the same scene again is instant). How quiet counts as a pause
follows the recording, so the audience's quiet between movements counts.

- The **Audio** column shows per marker: **✓ at a pause**, **pause
  +4.0 s** (with **snap** to move it there), or **no pause near**.
- Above the table: how many markers start at a pause — and when more
  would with all times shifted (the online video has a longer intro, say),
  that shift, with **shift** to apply it. **snap … onto the nearest
  pause** moves every marker that's a little off.
- Applause between works can hide a pause, and quiet passages can look
  like one — it's a hint, nothing changes unless you click.

The **Skip the check against the audio** setting switches it off (e.g. on
a slow server).

**Primary tag**: every marker needs one. A scraper can name it per marker;
otherwise the **Primary tag for scraped markers** setting is used (empty:
`Chapter`), and you can change it in the dialog. A primary tag that
doesn't exist yet is created. Other tags are matched by name or alias;
ones that don't exist are left out (and listed).

## Text in the wrong encoding

Old tools often write titles in Windows-1252 instead of UTF-8, which shows
up as "sch�nen" or "schÃ¶nen". This is set right everywhere — chapters in
the video file (read as raw bytes, before ffprobe could turn them into
"�"), its chapter track, chapter files next to it, text files you pick in
the dialog, and every scraper's titles and tags: "schönen".

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
- **Skip the check against the audio** — no pause check in the review
  dialog.
- **Fill in tags under** — parent tags whose tags are filled in from the
  titles (above); empty: `Composers`, `-` switches it off.

These were Marker Improvements' settings before this became a plugin of
its own; values set there are still used until you set them here.
