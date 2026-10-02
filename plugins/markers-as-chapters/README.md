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

- on top, the scrapers that work on the scene itself (its file) and the
  ones that read text (**… paste text or pick a file**);
- below the line, the scrapers for websites (arte.tv, ORF ON, online
  chapters): one entry per scene URL each handles, and **other URL…** to
  enter one. A URL a scraper for that very site handles isn't offered to
  the catch-all online chapters scraper too.

The markers found open in a dialog: tick the ones to create, change
titles, primary tag and tags, and **shift all times** (when the online
video has a longer or shorter intro than your file). Markers already in
the scene at that time are flagged and not ticked. **Create markers**
adds them, and the page updates. Also in the dialog:

- **The table is a timeline**: one row per marker in time order, each as
  tall as it lasts (with a minimum height for the fields; **Height** 1×–8×
  stretches it), and a row of its own for every gap between markers: a
  **pause** in light blue ("⏸ pause 0:20 · 30:10 – 30:30") when the audio
  is mostly quiet there — however long, applause included — or, when
  there's music in it, "… without a marker" in amber (before the audio
  check is done: gaps over 20 seconds). A strip on the left of each row shows its colour (blue: to
  create, grey: not ticked, orange: already a marker there, hatched: not
  music) and the pauses found in the audio as dark lines; **hovering** the
  strip shows that moment of the video (Stash's seek bar thumbnails, or
  the video itself if there are none) with its time.
- **Take the tags' names out of the titles** (on by default): a marker
  that got a tag — a composer — loses that name in its title: "Johann
  Strauss Sohn – Im Krapfenwaldl" → "Im Krapfenwaldl". First names,
  initials, van / von, Sohn / Vater / II and other spellings count. What
  the name leaves behind goes too — the separators around it, brackets it
  was in ("Im Krapfenwaldl (Johann Strauss)"), a "by" / "von" before it.
  Every title is tidied anyway: separators side by side become one, ones
  at the start or end go, unusual and double spaces become one space, and
  there's no space before a comma.
- **not music** per row — applause, a speech, an interview: no marker for
  it. When the titles were placed at the pauses (titles without times),
  all titles after it **move on** to the next pieces and the times are
  worked out again from the pauses; the dialog says if titles are left
  without a piece. **undo** takes it back.

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
- **Subtitles** — from a `.srt` / `.vtt` / `.ass` next to the video (also
  `Concert.de.srt`), from the video file's own subtitle track (text
  subtitles; picture ones can't be read), or online with yt-dlp — the
  scene's URLs or one you enter (ARTE, ARD, ZDF, ORF … have subtitles for
  some broadcasts); or paste them / pick a file (Plain text recognises
  them too). Concert subtitles show what's said or shown, not the music,
  so: entries less than 20 s apart make one group; a short one — a title
  card — gets a marker where it shows, an announcement (longer, or with
  "es folgt", "und nun", "wir beginnen mit" …) one where it ends. The title
  is the card's text or the announcement's last sentence without its
  lead-in ("Und nun der Radetzky-Marsch von Johann Strauss Vater" →
  "Radetzky-Marsch" + the composer tag). ♪ / "(Musik)" start music,
  "[Applaus]" ends it; "U/T" and the like are ignored. Many concerts have
  no subtitles at all; the dialog says where it looked.
- **Plain text** — paste text or pick a file (it's read in your browser,
  so from the device you're on), check and edit it, then **Scrape**. Every
  line with a time in it becomes a marker, the rest of the line its title;
  lines without a time are skipped. Times like `1:23`, `1:02:03`,
  `[12:34]`, `(5:10)`, `3m20s`; a range like `1:23 - 4:56` gives the end
  too, otherwise a marker ends where the next starts (the last at the end
  of the video). A **CUE sheet** works too: one marker per track, its
  PERFORMER as a tag. A pasted sheet with several FILE entries can't be
  used as it is — every file's tracks start at 0:00 again, and there are
  no files to measure; use it as **Chapter file next to the video**
  instead, with its audio files beside it.

  **JSON** — what **Copy as text → JSON** writes, and the chapter lists of
  other tools: medici.tv (chapters with composer, work and movement),
  ffprobe (`-show_chapters -of json`), yt-dlp's info file,
  Stash's own marker data, or any list of objects with a start (`seconds`,
  `start`, `start_time`, `time` …) and a title — times as seconds or as
  "1:02:03". Primary tags and tags come along. A CUE sheet copied out with
  **Copy as text** comes back with its primary tags, tags and ends too.

  **Programmes with durations**, as the BBC lists them — a composer on a
  line of their own, then their works with "(13 mins)" ("Unknown" is no
  composer; a work may have no duration). The pieces are placed by their
  durations and the pauses in the audio: each starts at the pause nearest
  to where the one before should end; without audio the durations are
  added up from 0:00. Titled "Composer – Work", with the composer as tag.

  **Tables** — a programme or tracklist in columns, split by tabs, `;`,
  `|`, several spaces or commas (also CSV with quotes), e.g. copied from a
  website or a spreadsheet. The columns are recognised by a header row
  (Zeit/Time, Dauer/Duration, Komponist/Composer, Titel/Werk/Title,
  Interpret/Performer, Nr.) or by their content: increasing times are
  start times, other times durations (added up from 0:00, as in a CD
  tracklist); 1, 2, 3 … is a track number; the column with repeated names
  is the composer, the one with work numbers ("op.", "Nr.") the title,
  another name column the performers. Markers are titled "Composer –
  Title", with the composer as a tag; the dialog says how the table was
  read ("tab-separated, 3 columns: start time, composer, title"). Without
  a time column the rows are placed at the pauses, as below.

  **Titles only** — no line has a time: the lines are taken as the pieces
  in order, e.g. the programme from ARD, BBC or the concert hall's site,
  which list the pieces but no times. The video is split at the longest
  pauses in its audio into exactly that many pieces, named in order (with
  too few pauses, shorter ones count too); the dialog says how many pauses
  were found, and which titles got no marker if there were too few.
  Reading the audio takes a while for a long concert on a small server —
  the dialog shows how long it's been working; the result is remembered,
  so the next time is instant.
- **Chapter file next to the video** — a file with the video's name next
  to it on the server: `Concert.cue`, `Concert.chapters.txt` (OGM
  chapters or a tracklist), `Concert.chapters.xml` (Matroska chapters, as
  from mkvextract), `Concert.ffmetadata`, `Concert.info.json` (yt-dlp) or
  `Concert.txt` (a tracklist) — also with the video's extension in the
  name (`Concert.mp4.cue`). A CUE sheet with several FILE entries (one per
  CD or side) starts every file's tracks at 0:00 again: the lengths of the
  audio files it names are added up (read with ffprobe), so each track
  gets its time in the whole recording. The files must be beside the
  sheet — by the name in the sheet, or just its file name (so
  `C:\Rips\side 2.flac` is found as `side 2.flac`). If one is missing or
  can't be read, the dialog says so. Also read: `Concert.markers.json`,
  `Concert.chapters.json` or `Concert.json` (see JSON under Plain text).

### Checked against the audio

Whatever the scraper, the review dialog also checks the markers against
the **pauses in the scene's own audio** — where pieces and movements
usually start. The pauses are found with ffmpeg (a few seconds to a
minute for a concert, the first time; it's remembered per file, so
scraping the same scene again is instant). How quiet counts as a pause
follows the recording, so the audience's quiet between movements counts.

- The **Audio** column shows per marker: **✓ at a pause**, **pause
  +4.0 s** (with **move +4.0 s**: the whole marker, start and end, moves
  by that amount, so it starts at the pause and keeps its length), or **no
  pause near**.
- Above the table: how many markers start at a pause — and when more
  would with all times shifted (the online video has a longer intro, say),
  that shift, with **shift** to apply it. **move … onto the nearest
  pause** moves every marker that's a little off, each by its own amount.
- Applause between works can hide a pause, and quiet passages can look
  like one — it's a hint, nothing changes unless you click.

The **Skip the check against the audio** setting switches it off (e.g. on
a slow server).

**Primary tag**: every marker needs one. A scraper can name it per marker;
otherwise the **Primary tag for scraped markers** setting is used (empty:
`Chapter`), and you can change it in the dialog. A primary tag that
doesn't exist yet is created. Other tags are matched by name or alias;
ones that don't exist are left out (and listed).

## Chapters offered by themselves

Open a scene that has no markers yet — or give it a URL, e.g. by scraping
it — and the quick sources are checked by themselves: a chapter file next
to the video (also a medici.tv JSON, whatever its name, if it's the only
one in the folder or its name matches the video's), the video's own
chapters, and ARTE / ORF ON through the scene's URLs. If chapters turn up,
a note at the bottom right says where and how many and asks whether to
import them — **Import…** opens the review dialog (nothing is saved until
**Create markers**; **Close** drops it all); **Not now** doesn't ask again
for that scene (in this browser).

## What you can paste

**Scrape markers… → Plain text — paste text or pick a file…** reads all of
these (or a file with them: .txt, .cue, .json, .srt, .vtt, .csv, .tsv). The
dialog says afterwards how the text was read; if it guessed wrong, edit the
text and scrape again.

**Times and titles** — one marker per line, the rest of the line is its
title. Times like `1:23`, `1:02:03`, `[12:34]`, `(5:10)`, `3m20s`; a range
gives the end too, otherwise a marker ends where the next starts.

```
0:00 I. Allegro con brio
7:41 - 17:30 II. Andante con moto
[1:02:03] Finale
```

**Titles only** — the pieces in order, without times; they're placed at
the pauses in the audio (the longest pauses split the video into that many
pieces).

```
I. Allegro con brio
II. Andante con moto
III. Scherzo
```

**A programme with durations**, as the BBC lists it — a composer on a line
of their own, then their works with their length; "Unknown" is no
composer. Placed by the durations and the pauses in the audio.

```
Giuseppe Verdi
Don Carlos – 'O don fatale'(5 mins)
Aida – Triumphal March(5 mins)
Unknown
The National Anthem (arr. Britten)(3 mins)
```

**A table** — columns split by tabs, `;`, `|`, several spaces or commas
(CSV with quotes too), e.g. copied from a website or a spreadsheet. A
header row (Zeit/Time, Dauer/Duration, Komponist/Composer, Titel/Werk/Title,
Interpret/Performer, Nr.) is optional — without one, the columns are
recognised by what's in them.

```
Zeit	Komponist	Werk
0:00	Johann Strauss	An der schönen blauen Donau
9:12	Johann Strauss Vater	Radetzky-Marsch
```

**A CUE sheet** — one marker per track; `REM PRIMARY_TAG`, `REM TAGS` and
`REM END` (as **Copy as text → CUE sheet** writes them) are read too.

```
TRACK 01 AUDIO
  TITLE "Overture"
  PERFORMER "Gioachino Rossini"
  INDEX 01 01:03:00
```

**JSON** — this plugin's own export (**Copy as text → JSON**), medici.tv's
chapters, ffprobe (`-show_chapters -of json`), yt-dlp's info file, Stash's
marker data, or any list of objects with a start and a title.

```json
{"chapters": [{"tc_start": 63, "tc_end": 476,
  "multiline_name": "Gioachino Rossini\nLa Scala di seta\nOverture",
  "work": {"composers": ["Gioachino Rossini"]}}]}
```

**Subtitles** (SRT or WebVTT) — announcements and title cards become
markers (see **Subtitles** above).

```
00:00:42,000 --> 00:00:47,000
Wir beginnen mit Franz von Suppè: Fatinitza-Marsch.
```

In every format, composers (and soloists) named in the titles are filled
in as tags, and text in the wrong encoding is set right.

## Text in the wrong encoding

Old tools often write titles in Windows-1252 instead of UTF-8, which shows
up as "sch�nen" or "schÃ¶nen". This is set right everywhere — chapters in
the video file (read as raw bytes, before ffprobe could turn them into
"�"), its chapter track, chapter files next to it, text files you pick in
the dialog, and every scraper's titles and tags: "schönen".

## Composers and other tags from the titles

Every scraper's markers get tags filled in from their titles: tags below
the **Fill in tags under** parent tags (default `Composers, Soloists` — the composer
tags [Tag Improvements](../tag-improvements/) keeps for performers marked
as composers) are found by

- their whole name or an alias, as whole words, or
- just the surname: "Beethoven: Symphony No. 5" → *Ludwig van Beethoven*.
  Only when one tag has that surname — two Bachs: neither, unless the
  title has more of the name. Spellings that differ only at the end count
  too (*Rachmaninow* / *Rachmaninoff*, *Mussorgski* / *Mussorgsky*); for
  others give the tag an alias.

Safeguards: the part of a title before the first separator (` - `, ` – `,
`: `, ` | `) is checked first — if it is exactly a tag's name or alias
("Johann Strauss Vater" → *Johann Strauss (Vater)*), that's the tag. A
"Vater" / "Sohn" (I / II, sen. / jun.) after a name has to fit the tag,
a surname alone doesn't count right after another composer's first name
("Johann Strauss" isn't Joseph Strauss), and a one-word alias doesn't count
inside a longer name of another tag.

Upper/lower case and accents (Dvořák / Dvorak) don't matter.

### For markers that already exist

**Scrape markers… → Composers from the titles…** does the same for the
scene's markers: it shows every marker where a composer tag named in the
title would be added and the title cleaned ("Johann Strauss Sohn -
Im Krapfenwaldl, Polka française op. 336" → *Johann Strauss* + "Im
Krapfenwaldl, Polka française op. 336"); untick what shouldn't change,
then **Apply**. Primary tag, times and other tags stay. For the whole
library at once: **Settings → Tasks → Composers from marker titles (all
scenes)** — every change is logged.

**Import missing composers** (at the top of that dialog): names before the
separator of titles that name no composer yet ("Karl Komzak Sohn -
Badner Madln" → "Karl Komzak Sohn") are listed, each looked up with the
[Classical Music](../../scrapers/ClassicalMusic/) scraper (searched
without Sohn / Vater / II …) — pick the right person in its dropdown (a
composer is preselected; "Sohn" prefers the junior, "Vater" the senior
one). **Import selected** creates the performers, tagged Composer, with
the name as the titles have it as an extra alias — so the composer tag
Tag Improvements makes from it matches those titles exactly — and the
proposals below are worked out again. The preview shows each title once,
with just the parts that go struck through.

### New composer

**Scrape markers… → New composer…** (also in the dialog above): enter a
name — a surname is enough — **Search**, and click the right one of the
results (with their short description, e.g. "österreichischer
Operettenkomponist (1819–1895)"). The performer is created with
everything the [Classical Music](../../scrapers/ClassicalMusic/) scraper
fills in — name, aliases, dates, country, portrait, Wikipedia text, links,
tags (missing ones are created) — plus the tag **Composer** (Tag
Improvements' **Composer performer tag**), so
[Tag Improvements](../tag-improvements/) makes the composer tag under
**Composers** right away. A performer who exists already just gets the
**Composer** tag. Needs the Classical Music scraper installed. A name the
scraper suggests (ARTE Concert's composers) is replaced by the matching
tag. The review dialog says how many markers got tags this way; change
them there as needed.

## Copying markers as text

**Copy as text…** in the review dialog gives the ticked markers as they'd
be created (with the shift, edited titles and tags; "not music" left out);
**Copy the scene's markers as text…** in the Scrape markers menu gives the
markers the scene already has. Formats:

- **Tracklist** — `0:00:02 Symphonie Nr. 5`: YouTube chapters, and the
  Plain text scraper reads it back;
- **With end times** — `0:00:02 – 0:30:10 Symphonie Nr. 5`;
- **Table**, tab-separated (start, end, title, tags) — pastes into a
  spreadsheet; Plain text reads it back too;
- **CUE sheet**, named after the video file — with everything: the title,
  the first tag as PERFORMER, and in `REM` lines (which players skip) the
  primary tag, all tags and the end; Plain text reads it back the same
  (times to 1/75 s, double quotes in titles become single ones);
- **JSON** — every field exactly (start, end, title, primary tag, tags);
  Plain text reads it back, and so does a `<video>.markers.json` next to
  the video;
- **ffmpeg chapters** (ffmetadata) — ffmpeg can write them into a video:
  `ffmpeg -i in.mp4 -i chapters.ffmetadata -map_metadata 1 -codec copy out.mp4`.

**Tags before the title** puts the tags (the composer) in front again,
for titles they were taken out of. **Copy** copies it (if the browser
won't — Stash on plain http — the text is selected for Ctrl+C / ⌘C);
**Download** saves it as a file.

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
