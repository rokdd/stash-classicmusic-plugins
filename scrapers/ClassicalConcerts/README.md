# Classical Concerts (Stash scene scraper)

Fills in scenes of concert recordings from the broadcasters' own pages —
**ARTE** (ARTE Concert), **ORF ON**, **ARD Mediathek**, **ZDF**, **3sat** and
**BBC** (programmes, iPlayer, Sounds).

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **Classical Concerts (ARTE, ORF, ARD, ZDF, 3sat, BBC)** and
**Install**. Needs Python 3 on the server, no extra modules.

## Use

Paste the page of the broadcast into the scene's URL field and scrape it
(**Edit → URL → scrape**), or **Scrape with… → Classical Concerts** for a
scene that already has such a URL.

## What's filled in

| Field | |
|---|---|
| Title | the broadcast's title (ARTE: with its subtitle, e.g. "… – Young Euro Classic 2026") |
| Details | the programme text; ORF adds its segments, the BBC its "Music played" list |
| Date | the concert's, when the text names one ("Alte Oper Frankfurt, 24. November 2023"), else the broadcast date (ARTE: the year of production) |
| Cover | the broadcaster's picture, in the largest size offered |
| Studio | the broadcaster or channel: ARTE, ORF III, hr, BR, 3sat, BBC Radio 3 … |
| Performers | orchestra, conductor, soloists, choir and composers — ARTE from its credits and chapters, the BBC from "Music played", everywhere also from the programme text ("Alain Altinoglu, Dirigent", "Giorgi Gigashvili (Klavier)", "Dirigent: …", "Johannes Brahms:", an orchestra on a line of its own) |
| Director | ARTE's "Regie" |
| URLs | the page |

Performers are matched to yours by name (or alias) when you save; new ones
can be created and then filled in with the
[Classical Music](../ClassicalMusic/) performer scraper.

ORF ON keeps videos only for a while; after that the page can't be scraped
any more.
