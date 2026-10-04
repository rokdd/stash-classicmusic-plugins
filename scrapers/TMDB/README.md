# TMDB (Stash scene scraper)

Fills in scenes from [The Movie Database](https://www.themoviedb.org) —
concert films, opera and ballet productions released on film or disc,
documentaries, and episodes of series.

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **TMDB** and **Install**. Needs Python 3 on the server, no extra
modules — and an **API key** (free: themoviedb.org → Settings → API; the
"API key" or the "API Read Access Token"). Stash has no settings for
scrapers, so put it in one of:

- **Settings → Plugins → Markers as Chapters → TMDB API key** (and **TMDB
  language**, default `de-DE`) — read through Stash's API (`STASH_URL`,
  default `http://localhost:9999`; `STASH_API_KEY` if Stash has a login);
- `config.json` next to `tmdb.py`: `{"api_key": "…", "language": "de-DE"}`
  (an update of the scraper may remove it);
- the environment of Stash: `TMDB_API_KEY`, `TMDB_LANGUAGE`.

## Use

- Paste a TMDB page into the scene's URL field and scrape it:
  `themoviedb.org/movie/…`, `/tv/…`, `/tv/…/season/n/episode/n`.
- **Scrape with… → TMDB**: by the scene's TMDB URL, else its title (or its
  file's name, without "1080p x264" and the like) and year — the film or
  series of that year first.
- Search by name: up to 15 films and series ("la traviata 2005" puts 2005
  first).

## What's filled in

Title, overview (in English when there's none in the language chosen),
release or air date, poster (an episode: its still), the production
company or network as studio, director, the cast and from the crew
director, composer, conductor, choreographer and stage director as
performers, genres as tags, the TMDB page as URL; an episode's code
(S01E02).
