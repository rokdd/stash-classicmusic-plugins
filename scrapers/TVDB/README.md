# TVDB (Stash scene scraper)

Fills in scenes from [TheTVDB](https://thetvdb.com) — episodes of series
(also recurring broadcasts like New Year's concerts, festival seasons) and
films.

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **TVDB** and **Install**. Needs Python 3 on the server, no extra
modules — and an **API key** (thetvdb.com → Dashboard → API keys; with a
user-supported key also your subscriber PIN). Stash has no settings for
scrapers, so put it in one of:

- **Settings → Plugins → Markers as Chapters → TVDB API key** (and **TVDB
  subscriber PIN**, **TVDB language**: three letters, default `deu`) —
  read through Stash's API (`STASH_URL`, default `http://localhost:9999`;
  `STASH_API_KEY` if Stash has a login);
- `config.json` next to `tvdb.py`: `{"api_key": "…", "pin": "…", "language": "deu"}`
  (an update of the scraper may remove it);
- the environment of Stash: `TVDB_API_KEY`, `TVDB_PIN`, `TVDB_LANGUAGE`.

## Use

- Paste a TVDB page into the scene's URL field and scrape it:
  `thetvdb.com/series/<name>`, `/series/<name>/episodes/<id>`,
  `/movies/<name>`.
- **Scrape with… → TVDB**: by the scene's TVDB URL, else its title (or its
  file's name) and year; with "S03E05" (or "S2022E01") in it, that
  episode.
- Search by name: up to 15 series and films.

## What's filled in

Title (series – S01E02 episode), overview and title in the language chosen
where TVDB has them, air or release date, picture, network or studio, the
people (cast, guests, hosts, director, composer) as performers, genres as
tags, the TVDB page as URL, an episode's code.
