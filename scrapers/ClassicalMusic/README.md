# Classical Music (Stash performer scraper)

Fills in performers for a classical music library — composers,
conductors, soloists, singers, orchestras and ensembles — from
[Wikidata](https://www.wikidata.org), with the
[Wikipedia](https://www.wikipedia.org) introduction as details and, for
composers, the epoch from [Open Opus](https://openopus.org).

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **Classical Music (Wikidata, Open Opus)** and **Install**. Needs
Python 3 on the server, no extra modules.

## Use

On a performer: **Edit → Scrape with… → Classical Music (Wikidata, Open
Opus)**.

- **Search by name** — German and English names, also just a surname
  ("Mutter", "Karajan", "Bach"). Only musicians, composers, conductors,
  singers, orchestras and ensembles are offered (other people only if
  there's no musician), each with its short description ("russischer
  Pianist, Komponist und Dirigent (1873–1943)") to pick the right one.
- **By link** — a Wikidata (`wikidata.org/wiki/Q…`), Wikipedia (any
  language) or MusicBrainz artist link in the performer's URL field.

## What's filled in

| Field | From |
|---|---|
| Name | Wikidata, in German, else English |
| Aliases | the other names and spellings on Wikidata (Latin-script languages): Rachmaninoff, Rachmaninow, Rachmaninov … |
| Birthdate, Death date | Wikidata, as exact as known (a year alone if that's all) |
| Gender | Wikidata |
| Country | where the person was born, as today's country (Bonn → DE); an ensemble's own country |
| Image | the portrait on Wikimedia Commons, else Open Opus's |
| Details | the Wikipedia introduction, German, else English |
| URLs | Wikipedia (de, en), Wikidata, MusicBrainz, IMSLP, Discogs, official website |
| Tags | the roles — Composer, Conductor, Pianist, Violinist, Soprano … (not teacher, musicologist and the like) — or the kind of ensemble (Symphony orchestra, Choir …), and a composer's epoch from Open Opus (Baroque, Classical, Early Romantic, Romantic, Late Romantic, 20th Century …) |

The **Composer** tag works with [Tag Improvements](../../plugins/tag-improvements/):
it keeps a tag per composer, so markers can carry them.

The languages are set at the top of `classical_music.py` (`LANGUAGES`).
