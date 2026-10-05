# MediathekView (Stash scene scraper)

Fills in scenes from the German-language public media libraries — ARD and
its stations, ZDF, 3sat, ARTE, Phoenix, KiKA, ORF, SRF, DW … — as
[MediathekView](https://mediathekview.de) lists them. Also broadcasts long
gone: MediathekView's [archive](https://archiv.mediathekview.de) has the
whole film list of every day since March 2015. No account, no API key.

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **MediathekView** and **Install**. Needs Python 3 on the server,
no extra modules.

## Use

- **Scrape with… → MediathekView** on a scene: finds the broadcast that
  fits best — by the scene's title or its file's name, its date (else a
  date in the name, else the file's date: recordings are usually saved the
  day they aired) and the file's length. First what's online now
  ([MediathekViewWeb](https://mediathekviewweb.de)'s search), then the
  archive's lists of the day and the week after the date (25–80 MB each,
  read while they download — a few seconds).
- **Edit → Scrape … → MediathekView**, search by name: up to 15 broadcasts
  online now; with a date in the words ("last night of the proms
  08.09.2018") that day's broadcasts from the archive too.

## What's filled in

| Field | |
|---|---|
| Title | the broadcast's title; its topic in front when that says more of what was looked for ("Last Night of the Proms 2018 – Live aus London") |
| Details | MediathekView's description (often shortened by the station) |
| Date | the broadcast date |
| Studio | the station: NDR, 3Sat, ARTE.DE, ORF … |
| URLs | the Mediathek page — if it's still there, [Classical Concerts](../ClassicalConcerts/) can scrape the performers from it |

MediathekView has no pictures. Reading the archive needs Python's `lzma`
module or the `xz` program on the server (some self-built Pythons lack
`lzma`: `apt install xz-utils` then); without either, only what's online
now is searched and the log says so. The file's name, length and date are read
through Stash's API on the same machine (`STASH_URL`, default
`http://localhost:9999`; `STASH_API_KEY` if Stash has a login).
