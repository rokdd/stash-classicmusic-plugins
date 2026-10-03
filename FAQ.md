# FAQ — how the plugins and scrapers work together

For a library of concert and opera recordings. Each answer says which
plugin or scraper does what; the details are in their READMEs.

**The pieces:**

| | What it's for |
|---|---|
| [Scene Improvements](plugins/advanced-file-operations/) (plugin) | the video files: convert to H.265, split at markers, repair; torrent check, yt-dlp downloads, task history |
| [Marker Improvements](plugins/marker-improvements-plugin/) (plugin) | markers on the seek bar and in the Markers tab, editing them |
| [Markers as Chapters](plugins/markers-as-chapters/) (plugin) | importing chapters as markers, from anywhere — and composers in their titles |
| [Tag Improvements](plugins/tag-improvements/) (plugin) | tag search and tree; a tag of their own for every composer and soloist |
| [Classical Music](scrapers/ClassicalMusic/) (performer scraper) | composers, soloists, conductors, orchestras from Wikidata |
| [Classical Concerts](scrapers/ClassicalConcerts/) (scene scraper) | a concert's page at ARTE, ORF ON, ARD, ZDF, 3sat, BBC, medici.tv |
| [Sidecar / local files](scrapers/Sidecar/) (scene scraper) | the files next to the video: medici.tv JSON, NFO, yt-dlp info, cover |

Plugins: Settings → Plugins, source `https://rokdd.github.io/stash-classicmusic-plugins/main/index.yml`.
Scrapers: Settings → Metadata Providers → Available Scrapers, source
`https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml`.

---

## Use cases

### I recorded a concert from ARTE / ORF / ARD / ZDF / 3sat / the BBC. How do I get everything in?

1. **The scene**: on the scene's Edit tab, paste the broadcast's page into
   the URL field and scrape it with **Classical Concerts** — title,
   programme text, concert date, cover, broadcaster as studio, orchestra,
   conductor, soloists and composers as performers.
2. **The performers**: new ones can be filled in with **Classical Music**
   (Edit → Scrape with…) — portrait, dates, Wikipedia text, roles as tags.
3. **The markers**: in the Markers tab, **Scrape markers…** — for ARTE and
   ORF ON the broadcaster's chapters (one per work), otherwise paste the
   programme into **Plain text**. A scene without markers usually offers
   its chapters by itself (a note at the bottom right).
4. **Check the times**: the review dialog compares every marker with the
   pauses in the audio; **move** / **shift** fix markers that are a little off.

### I downloaded a concert from medici.tv and saved its JSON. What now?

Put the JSON next to the video — any name works if it's the only medici.tv
JSON in that folder. Then:

- **Scene**: Edit → **Scrape with… → Sidecar / local files** (or Classical
  Concerts) — title, description, date, cast, composers, director,
  festival and venue.
- **Markers**: save the scene; **Markers as Chapters** notices the chapters
  in the JSON and offers to import them. Or Scrape markers… → **Chapter file
  next to the video**.

medici.tv's chapters and full cast are only in the JSON (they need a
medici.tv login); its page alone gives title, date, picture and the cast in
the subtitle.

### I have only the programme — the pieces, but no times (ARD, BBC, a concert hall's site).

Scrape markers… → **Plain text**, paste the titles one per line. Without
times they're placed at the pauses in the audio: the longest pauses split
the video into as many pieces as there are titles. A list with durations
("Aida – Triumphal March(5 mins)", as the BBC writes it) is placed by the
durations and the pauses. In the dialog, **not music** on a row (applause,
a speech) moves the following titles on to the next pieces.

### My video file has chapters, but every one starts at 0:00 (or the titles are "nan", "Init" …).

**Video file chapters** handles that: junk titles are left out; when all
start at 0:00, the MP4's chapter track is read directly. If there are no
times anywhere, it creates no markers but lists the titles — paste them
into **Plain text**, and they're placed at the pauses.

### The marker titles name the composer ("Johann Strauss Sohn – Im Krapfenwaldl"). Can that become a tag?

Yes:

1. Make sure the composer has a tag: a performer tagged **Composer** (the
   Classical Music scraper does that) gets a tag of their own under
   **Composers** from Tag Improvements.
2. Scrape markers… → **Composers from the titles…** shows each marker that
   would change — the name struck through, the composer tag added — and
   **Apply** does it. For the whole library: Settings → Tasks →
   **Composers from marker titles (all scenes)**.
3. Names that aren't artists in Stash yet are listed at the top as
   **Import missing artists**: pick the right person from Wikidata, tick
   **is a composer** or not, **Import selected**.

When markers are imported, their composers are filled in the same way, and
tags that don't exist yet are asked about before anything is created.

### I want soloists (and maybe conductors) as tags too, not only composers.

Tag Improvements → **Performer roles**, e.g.
`Composers: Composer; Soloists: Pianist, Violinist, Soprano, …; Conductors: Conductor`.
Every performer with one of those roles (a performer tag, or the custom
field `roles`) gets a tag under the matching parent; someone who's both
gets one tag under both. Markers as Chapters fills in tags under
**Composers, Soloists** (its setting **Fill in tags under**).

### I imported markers before, without the composers. Can I add them now?

Either **Composers from the titles…** (above), or import again: rows where
a marker already exists say "already a marker here — tick to update it";
ticked, that marker gets the new title and tags instead of a second marker
being made.

### I want the chapters elsewhere — in the video file, a CUE sheet, a spreadsheet.

Scrape markers… → **Copy the scene's markers as text…** (or **Copy as
text…** in the review dialog): tracklist, with end times, table, CUE sheet,
ffmpeg chapters, JSON. CUE and JSON keep everything (primary tag, tags,
ends) and can be pasted back with Plain text.

### Can subtitles help?

Sometimes: **Subtitles** reads a .srt / .vtt next to the video, the video's
own subtitle track, or the broadcaster's (yt-dlp); **Subtitles from
OpenSubtitles** looks them up on opensubtitles.com (API key and account in
the settings). Announcements and title cards become markers, in operas
each sung number (titled with its first line). Concerts often have none —
operas and films more often.

### Can OpenSubtitles find the subtitles for my file?

Yes, by the file's fingerprint (size and a checksum of its start and
end): subtitles made for exactly your release fit to the second. With an
API key set, a scene without markers is checked when you open it and the
subtitles are offered — the check costs no downloads. Otherwise the title
is searched; when it picks the wrong production, use **search with your
own words…** with the year or the place.

---

## Problems

### "Scrape with…" says nothing was found / "EOF".

- The scene has no URL of a site the scraper knows: Classical Concerts
  needs a broadcaster's page; for files next to the video use **Sidecar**.
- The page isn't there any more (ORF ON keeps videos for weeks; medici.tv
  unpublishes programmes) — the log (Settings → Logs) says so.
- Sidecar / Classical Concerts ask Stash for the video's path at
  `http://localhost:9999`; if Stash runs elsewhere or has a login, set
  `STASH_URL` / `STASH_API_KEY` in Stash's environment.
- After an update, Settings → Metadata Providers → **Check for updates** —
  an old version may still be installed.

### A tag was left out when importing markers.

Tags that don't exist yet are asked about before the markers are created
(make a performer from Wikidata, a plain tag, or leave it out), and asked
again if creating them failed — nothing is left out unless chosen. If it
still happens, check that Markers as Chapters is up to date.

### I changed a marker's end, but the list still shows the old one.

Check the marker was saved — Stash's form doesn't save without a primary
tag. Marker Improvements reloads after every save; update it if it doesn't.

### I can't edit a marker's title — it's only a dropdown.

That's Stash's field (titles used before). Click **✎** next to it
(Marker Improvements): it becomes a text box with the current title.

### Opening another marker while one is being edited does nothing.

Fixed in Marker Improvements: the open form is cancelled first (Stash
shows no marker list while a form is open). Update it.

### The tag dropdown doesn't find a tag I know exists.

Tag Improvements searches every word, in any order, in names, aliases,
descriptions and parent tags — unless **Use Stash's plain tag search** is
on. The **⤢ Larger, with images** switch at the top of every tag dropdown
shows the images and descriptions.

### My conversion isn't in the task history.

Scene Improvements' own tasks (convert, split, repair) record themselves
when they end, also without a page open. Other tasks are recorded while a
Stash page is open (and caught up from Stash's last 10). See Settings →
Tools → **Task history**.
