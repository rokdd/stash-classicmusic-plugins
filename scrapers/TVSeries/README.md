# TV & concert series (Stash scraper)

Finds the series a recording belongs to on **Wikipedia** and **Wikidata** —
a recurring concert ("Neujahrskonzert der Wiener Philharmoniker"), a
festival or concert series ("Proms", "Lucerne Festival"), a TV series —
and puts the scene into a **group** of that name: the article's
introduction as synopsis, its picture, the article as URL, the series'
genres (Wikidata) as tags, its broadcaster as the group's studio.

## Install

**Settings → Metadata Providers → Available Scrapers → Add Source**, any
name and `https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`,
then tick **TV & concert series (Wikipedia)** and **Install**. Python 3, no
extra modules, no account.

## Use

- On a scene: **Edit → Scrape with… → TV & concert series (Wikipedia)**.
  Stash shows the group; save, and the group is made (or the existing one
  of that name used). The scene keeps its own title and details.
- On a group: paste the series' Wikipedia article as its URL and scrape it.
- Search by name: series found by those words.

## How sure it is

It tries the runs of words of the scene's title or file name as article
titles, in the German and English Wikipedia ("proms.Last Night Of The Proms
2018-Bbc-Fassung" → "Last Night of the Proms" → the article "Proms");
the longest run that leads to an article wins. Then Wikipedia's search,
where an article only counts if all words of its title are in the scene's
name. And only what Wikidata calls a series, programme, recurring event,
festival or concert series is taken — not an orchestra, a person, a place,
a disambiguation page. Rather nothing than a wrong series.

The scene's file name is read through Stash's API on the same machine
(`STASH_URL`, default `http://localhost:9999`; `STASH_API_KEY` if Stash has
a login).
