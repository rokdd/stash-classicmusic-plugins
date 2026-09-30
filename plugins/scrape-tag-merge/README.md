# Scrape Tag Merge (Stash plugin)

When you scrape a scene from its **Edit** tab — **Scrape with…** a scraper
or StashDB — Stash normally *replaces* the scene's tags with the scraped
ones. With this plugin the scrape dialog offers the scene's **existing
tags plus the scraped ones** instead.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/scrape-tag-merge

## What you see

In the scrape dialog's **Tags** row, the scraped (right) side lists:

1. the scene's current tags, then
2. the scraped tags that matched a tag you already have and aren't on the
   scene yet, and
3. scraped tags Stash couldn't match to one of your tags — with their
   usual create/link buttons.

Everything else about the dialog is Stash's own: you can remove tags on
the right before applying, or pick the left (existing) side to keep the
tags as they were. Other fields — title, date, performers, … — behave as
before.

The Tagger view isn't affected; it has its own merge setting.

## Settings

Settings → Plugins → Scrape Tag Merge → **Replace tags instead (Stash's
default)**: turn on to get Stash's usual replace behaviour back.

## How it works

The scrape dialog gets its data from Stash's scrape queries
(`scrapeSingleScene`, `scrapeSceneURL`). The plugin watches the page's
requests and, for those answers only, adds the scene's current tags to
the scraped tag list before the dialog reads it — so no part of Stash's
own page is patched. Only on a scene's own page, and if anything goes
wrong it leaves Stash's answer untouched.

Scenes only for now; galleries and images scrape the same way and can
follow.
