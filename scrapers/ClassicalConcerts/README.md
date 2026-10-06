# Classical Concerts (Stash scene scraper)

Fills in scenes of concert recordings from the broadcasters' own pages —
**ARTE** (ARTE Concert), **ORF ON**, **ARD Mediathek**, **ZDF**, **3sat** and
**BBC** (programmes, iPlayer, Sounds) and **medici.tv**.

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **Classical Concerts (ARTE, ORF, ARD, ZDF, 3sat, BBC)** and
**Install**. Needs Python 3 on the server, no extra modules.

## Use

Paste the page of the broadcast into the scene's URL field and scrape it
(**Edit → URL → scrape**), or **Scrape with… → Classical Concerts** for a
scene that already has such a URL.

**Press releases** of the broadcasters (NDR, Das Erste, ZDF, WDR, BR, SWR,
MDR, hr, ARTE, ORF, SRF, presseportal.de) — often all that's left of an old
broadcast: paste the release's page as the scene's URL. Read: the title
(what's in quotes in the headline, "The Last Night of the Proms 2008"), the
text, the broadcast date and channel from its "Sendetermin: Sonnabend,
13. September, 22.10 Uhr, NDR Fernsehen" (the year from the release), and
the performers and composers named in it. A link copied from Google's
results (google.com/url?…) works too.

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

**medici.tv**: from its page (medici.tv/en/concerts/…, operas, ballets …)
the title, recording date, picture and — from the subtitle — the cast
("Thomas Adès (conductor) — With …"); the chapters and full cast need a
medici.tv login. If you've saved medici.tv's JSON for a programme (with a
login, from its site), put it next to the video as `<video>.medici.json`
(or `<video>.json`) and use **Scrape with… → Classical Concerts**: then
also the description, the whole cast, composers, director, festival and
venue (as tags). For that the scraper asks Stash for the video's path at
`http://localhost:9999` — set `STASH_URL` (and `STASH_API_KEY` if Stash has a
login) in Stash's environment if it runs elsewhere. The same JSON gives
the chapters in Markers as Chapters (Plain text, or as a chapter file next
to the video).

ORF ON keeps videos only for a while; after that the page can't be scraped
any more.
