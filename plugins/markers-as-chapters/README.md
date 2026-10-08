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
the scene at that time are flagged and not ticked — tick one to **update**
that marker instead (e.g. to add the composers after an earlier import
without them): it gets the new title and the new tags on top of its own;
primary tag and times stay. **Create markers** adds and updates them, and
the page updates. Also in the dialog:

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
  "[Applaus]" ends it; "U/T" and the like are ignored. A long group of
  sung text (an opera's number: more than 8 entries or a minute) gets a
  marker where it begins, titled with its first line ("Libiamo, ne' lieti
  calici …"). Many concerts have
  no subtitles at all; the dialog says where it looked.
- **Subtitles from OpenSubtitles** — subtitles from opensubtitles.com,
  turned into markers like **Subtitles** does. Found by the file's
  fingerprint (exact, when your file is the release the subtitles were
  made for — an opera DVD, say), else by the scene's title. Of several,
  the one with the scene's year comes first, then the one sharing the most
  words with the scene's title and file name (in its title and release
  name: "Salzburg 2006 DVDRip"), then the preferred language, then the
  most downloaded; the dialog names the next ones. Not the right
  production? **Subtitles from OpenSubtitles — search with your own
  words…** in the menu ("la traviata salzburg 2005"). When you open a
  scene without markers, the plugin checks by the fingerprint whether
  there are subtitles made for exactly this file and offers them (a search
  only — it costs none of your downloads). Needs an **OpenSubtitles API
  key** (free at opensubtitles.com, under API consumers) and, to download,
  your **OpenSubtitles username** and **password** (about 20 downloads a
  day with a free account) — in the plugin's settings, with **OpenSubtitles
  languages** (default `de,en`). Live concerts are rarely there; operas and
  films are. The dialog says which subtitles were used and how many
  downloads are left today.
- **Text in the picture (OCR)** — reads what's written in the video
  itself: the captions broadcasters show when a piece begins ("HOMEWARD
  BOUND", "Sergej Rachmaninow / Klavierkonzert Nr. 3"), title cards,
  burned-in subtitles. Where pieces begin — the start of the video and the
  45 seconds after each pause in the audio (the whole video only when
  there are no pauses) — a frame every 4 seconds goes to **tesseract** on
  the Stash server. Then:
  - words it's less than 60 % sure of are dropped; a line counts with two
    real words or more (three letters each, most of the line) — a logo
    read as "NDRID", a backdrop's "Proms", bits of the picture drop out;
  - a line read before — anywhere, in capitals or not, with small reading
    differences — isn't new and is left out; a text in most frames (a
    channel's logo) too;
  - sounds described — "(Applaus)", "[Beifall]", "WHISTLING", "*Pfiffe*",
    "♪ Musik ♪", also when the brackets weren't read — are left out;
    applause ends a piece;
  - texts less than 30 seconds apart (and no applause between) are one
    marker (a song's lines, a caption), titled by the line most like a
    caption: in capitals, with "op." / "Nr." / "BWV" / a colon, short —
    not one going on (a comma at the end, a small first letter); else the
    first line.

  These steps run on what was read: changing them doesn't read the video
  again. Frames the same as the one before aren't read again; several are
  read at once (one per processor core), in one language (the first; set
  more in **Languages of text in the picture** — each makes it slower).
  It runs as a **Stash task** ("Text in the picture: <file>" in Settings →
  Tasks and the job indicator, where it can be stopped; Stash runs its
  tasks one after another): closing the dialog or the page doesn't stop
  it — open it again later and the markers are there. The dialog follows
  the task (waiting in the queue, how far, how long). What's read is saved
  every minute, so a run that's stopped goes on from there; it's kept in
  Stash's generated folder. Needs tesseract — Debian / Ubuntu: `apt
  install tesseract-ocr tesseract-ocr-deu`; Stash's Docker image: `apk add
  tesseract-ocr tesseract-ocr-data-deu` — else the menu entry is turned
  off and says so.
- **Turned off when there's nothing:** when the menu opens, the scene is
  checked in the background — a chapter file next to the video, chapters
  and subtitles in it, ARTE / ORF ON through its URLs, the OpenSubtitles
  key. Entries that would find nothing are greyed out with the reason
  ("No chapter file next to the video …"), those that found something say
  how many markers; a scrape that comes back empty turns its entry off
  too. **↻ Check again** at the bottom forgets it (after adding a file,
  say).
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

**Tags that don't exist yet** — composers from the chapters, mostly — are
listed when you click **Create markers**, each with what will happen:
**Create performer from Wikidata** (the person the
[Classical Music](../../scrapers/ClassicalMusic/) scraper finds for the
name — created with portrait, dates and Wikipedia text; with **is a
composer** ticked — preselected when Wikidata calls them one — tagged
Composer, so Tag Improvements files their tag under Composers; unticked,
their roles decide: a pianist or soprano goes under Soloists), **Create a
plain tag**, or **Leave it out**. **Continue** works through them and shows every
step (searching, creating the performer, waiting for the tag …); a tag that
still doesn't exist afterwards is asked about again — try the composer
again, make a plain tag or leave it out — so nothing is left out unless
you chose so. Then the markers are created with all their tags, and the
report lists the composers and tags created. **Back to the markers**
returns to the table.

**Primary tag**: every marker needs one. A scraper can name it per marker;
otherwise the **Primary tag for scraped markers** setting is used (empty:
`Chapter`), and you can change it in the dialog. A primary tag that
doesn't exist yet is created. Other tags are matched by name or alias;
ones that don't exist are left out (and listed).

## Chapters offered by themselves

Open a scene that has no markers yet — or save it, e.g. after scraping it
(also with the Sidecar scraper) — and the quick sources are checked by
themselves: a chapter file next
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

**Import missing artists** (at the top of that dialog): names before the
separator of titles that name no artist in Stash yet ("Karl Komzak Sohn -
Badner Madln" → "Karl Komzak Sohn") are listed, each looked up on
Wikidata with the [Classical Music](../../scrapers/ClassicalMusic/) scraper
(searched without Sohn / Vater / II …) — pick the right person in its
dropdown (a composer is preselected; "Sohn" prefers the junior, "Vater"
the senior one) and whether they're **a composer** (ticked when Wikidata
says so). Each row says what will happen. **Import selected** creates the
performers, with the name as the titles have it as an extra alias, shows
for each how it went, and Tag Improvements makes their tags — under
Composers if ticked, else where their roles put them (a pianist or soprano
under Soloists); then the proposals below are worked out again, and a name
whose import failed is listed again. The preview shows each title once,
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

## The chapter editor

The **Markers tab** shows it in place of Stash's marker list (switch **Chapters | Stash's list** next to the buttons, remembered in the browser; while Stash's own marker form is open — Create Marker, editing one — the tab is Stash's). Also as a dialog: **Scrape markers… → Chapter editor** — one panel for a scene's chapters:

- **All sources in one table:** the markers in Stash, and with **Add from**
  whatever a scraper finds (the file's chapters, a chapter file, ARTE,
  subtitles, text in the picture, pasted text …). A chapter at the same
  time (±5 s) gets it as an alternative — take its **title**, **times** or
  **tags** with one click — the rest come in as new chapters.
- **Tools for all chapters:** **Clean titles & composers** (composers named
  in the titles become tags, the titles lose their names), **Extend to the
  next pause** (each chapter ends where the audio's next pause begins, never
  past the next chapter), **Starts onto the pauses**, **Shift all**, and a
  new chapter **at the player**'s position.
- **Overview:** the whole scene as a bar — chapters in Stash blue, changed
  orange, new green, to be deleted red, the pauses light blue; click one to
  get to its row.
- **Columns** (time, title, primary tag, tags, source, audio) can be hidden;
  remembered in the browser.
- **Save** creates, updates and deletes in one go; tags that don't exist
  yet are asked about first, as when importing.

## Composers of scene and chapters in step

On the scene a composer is a **performer**, on a chapter a **tag** (markers
have no performers): the composer tags under **Composers** (the first of
**Fill in tags under**), each named like its performer — the tags Tag
Improvements keeps. Kept in step when a scene or a marker is saved (and by
**Settings → Tasks → Composers of scenes and chapters in step**):

- a chapter's composer is added to the scene's performers;
- when the scene has exactly one composer, chapters without one get its tag;
  when the scene's composer changes, the chapters that got it follow;
- what you take away yourself stays away: a composer removed from a
  chapter isn't added to it again, a performer removed from the scene isn't
  added to the scene again (remembered in `.composer-sync.json` in the
  plugin's folder).

Switched off by **Don't keep composers of scene and chapters in step**.

## Markers and the scene's files

A marker's time belongs to the file it was set on — Stash doesn't keep
which one. When scenes are **merged**, all their markers move to the one
scene with their times unchanged; when the **primary file changes**, the
markers stay as they are. If the files differ in length (another cut, an
intro more or less, a broadcast vs. a disc, PAL speed), the markers set on
the other file are then off.

- **Which file**: Markers as Chapters remembers the file each marker was
  set on (`.marker-files.json` in the plugin's folder) — new markers by
  themselves (a hook, when a marker is created or its time changed); for
  the markers you already have, run **Settings → Tasks → Remember each
  marker's file** once (it covers every scene with one file — best before
  merging).
- **Noticed by itself**: on a scene with several files where markers were
  set on a file of another length than the primary one, a note at the
  bottom right says so — **Line them up…**.
- **Scrape markers… → Markers and the scene's files…**: the files with
  their lengths and markers. Pick the file the markers were set on,
  **Compare the audio**: the two files' loudness (every half second, as
  for the pause check) is compared — first as a whole (also at PAL / film
  speed), then in the two minutes around each marker, so a cut-out intro
  or a piece missing in between is followed. Each row shows the old and
  the new time (and end); markers that fall into a part the primary file
  doesn't have are left unticked. After a merge, a marker that lands where
  the same piece already has one is offered for deleting instead.
  **Apply** moves them and remembers the primary file for them.
- **Compare the picture** instead: every marker is looked for itself in
  the primary file by its first four seconds of picture (eight tiny
  frames, so movement tells a still shot apart) — starting where the
  marker before suggests, within 45 seconds, further around if nothing
  fits there. So a shift that changes anywhere in between (an advert cut,
  a piece missing) is followed, and it works when the sound differs
  (another language, commentary). The speed (PAL / film) is worked out
  from all markers found; an end is placed with the next marker's start
  or looked for itself. Slower than the audio: some seconds per marker.

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

## Where the analyses are kept

In Stash's **generated** folder (Settings → System → Application Paths),
under `markers-as-chapters/`: `audio` (the loudness of each video's
audio — for the pauses and for lining up files), `frames` (what was read
in the picture), `progress` (how far a long scraper is). They're only
remembered work — delete them any time, they're made again when needed.
Each is tied to the file (path, size, date) and to how it was analysed, so
a changed file or a new version of the analysis is analysed afresh. If the
generated folder can't be written to, the plugin's own folder is used.

Which file each marker was set on is kept in the plugin's folder
(`.marker-files.json`) — that's not generated: it can't be made again.
Updating the plugin leaves it alone.

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
- **OpenSubtitles API key / username / password / languages** — for
  Subtitles from OpenSubtitles (above).
- **tesseract** — its path, for Text in the picture; empty: on the PATH.
- **Languages of text in the picture** — e.g. `de,en` (each needs
  tesseract's language pack); empty: the OpenSubtitles languages.

These were Marker Improvements' settings before this became a plugin of
its own; values set there are still used until you set them here.
