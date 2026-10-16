# Stash classic music plugins

Plugins for [Stash](https://stashapp.cc), made for a library of concerts
and classical music recordings — but useful for any library.

| Plugin | What it's for |
|---|---|
| [Scene Improvements](plugins/advanced-file-operations/) | Convert to H.265, split a scene at its markers, repair a broken file, join a recording's parts (VDR); a torrent check, yt-dlp downloads and a task history |
| [Marker Improvements](plugins/marker-improvements-plugin/) | Tag images on the video's seek bar, click-to-edit markers |
| [Markers as Chapters](plugins/markers-as-chapters/) | Import chapters as markers from anywhere — the video file or a file next to it, YouTube, ARTE Concert, ORF ON, subtitles (also OpenSubtitles), text in the picture (OCR), a pasted tracklist or programme — checked against the pauses in the audio; composers from the titles, kept in step with the scene; markers lined up after merging scenes |
| [Marker Editor for Chapters](plugins/marker-editor-for-chapters/) | A scene's chapters in one table — in the Markers tab: add from every source, combine duplicates, clean titles and composers, extend to the next pause, play statistics, save at once (uses Markers as Chapters) |
| [Tag Improvements](plugins/tag-improvements/) | A tag tree on the Tags page, a better tag search (also as a grid of tiles), tag descriptions from StashDB, scraping that adds tags instead of replacing them, and a tag for every composer and soloist kept in step with the performers |
| [Face Identifier](plugins/face-identifier/) | Who's in a scene, by their faces: learns your performers' faces from their portraits, shows who's recognised in the video (add them), the unknown faces (say who — learnt), and optionally Visage's answer |

They're independent of each other — install any of them.

And scrapers:

| Scraper | What it's for |
|---|---|
| [Classical Music](scrapers/ClassicalMusic/) | Performers: composers, conductors, soloists, orchestras from Wikidata — Wikipedia text, portrait, dates, country, roles and (Open Opus) the composer's epoch as tags |
| [Classical Concerts](scrapers/ClassicalConcerts/) | Scenes from ARTE (ARTE Concert), ORF ON, ARD Mediathek, ZDF, 3sat, BBC and medici.tv — title, programme, concert date, cover, broadcaster, and orchestra, conductor, soloists and composers as performers |
| [Sidecar / local files](scrapers/Sidecar/) | Scenes from the files next to the video: a medici.tv JSON, a Kodi / Jellyfin NFO, yt-dlp's .info.json and a cover image |
| [MediathekView](scrapers/MediathekView/) | Scenes from the German-language public media libraries (ARD, ZDF, 3sat, ARTE, ORF, SRF …) — what's online now, and from MediathekView's archive every broadcast since 2015; no key needed |
| [TMDB](scrapers/TMDB/) | Scenes from The Movie Database — concert films, opera and ballet productions, documentaries, series episodes (API key) |
| [TVDB](scrapers/TVDB/) | Scenes from TheTVDB — series episodes, recurring broadcasts, films (API key) |
| [TV & concert series](scrapers/TVSeries/) | The series a recording belongs to — a recurring concert, festival, concert or TV series — from Wikipedia and Wikidata, as the scene's group (synopsis, picture, genres) |

**How do they work together?** The [FAQ](FAQ.md) goes through typical
use cases (a recorded concert, a medici.tv download, composers in marker
titles …) and problems, step by step.

## Install

1. In Stash, open **Settings → Plugins → Available Plugins** and click
   **Add Source**.
2. Enter any name (e.g. `Classic music plugins`) and this URL:
   ```
   https://rokdd.github.io/stash-classicmusic-plugins/main/index.yml
   ```
3. The plugins now show up under that source. Tick the ones you want and
   click **Install**.
4. Reload the page in your browser.

**Updating:** Settings → Plugins → **Check for updates**, then update the
ones listed. Afterwards, reload the page — and hard-refresh (Ctrl+Shift+R)
if a change doesn't show up, so the browser doesn't keep the old script.

**Without the source:** copy a plugin's folder from [plugins](plugins/)
into your Stash plugins directory (Settings → Plugins shows where), then
Settings → Plugins → **Reload plugins**.

### The scrapers

1. **Settings → Metadata Providers → Available Scrapers → Add Source**,
   any name (e.g. `Classic music scrapers`) and this URL:
   ```
   https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml
   ```
2. Tick **Classical Music (Wikidata, Open Opus)**, **Classical Concerts** and
   **Sidecar / local files** and click **Install**.
3. On a performer: **Edit → Scrape with… → Classical Music**, search by
   name (also just a surname: "Mutter", "Karajan") and pick the right
   one — or paste a Wikidata, Wikipedia or MusicBrainz link into the URL
   field and scrape that.
4. On a scene: paste the broadcaster's page into the scene's URL field and
   scrape it, or **Scrape with… → Classical Concerts** for a scene that
   already has such a URL.

Both need Python 3 on the server (no extra modules).

### Extra setup for Scene Improvements

This one runs ffmpeg on the server, so the machine Stash runs on needs:

- **ffmpeg and ffprobe with H.265 support** (`libx265`). Check with
  `ffmpeg -hide_banner -encoders | grep libx265`. Debian/Ubuntu's own
  `ffmpeg` package has it.
- **Python 3 with the `requests` module.** On Debian/Ubuntu:
  `sudo apt install python3 python3-requests` (`pip install` is blocked
  there). Elsewhere: `pip install -r requirements.txt` from the plugin
  folder.
- If Stash can't find Python (there's no `python` command, only
  `python3`), set Settings → System → **Python executable path** to e.g.
  `/usr/bin/python3`.

**Tag Improvements** also runs on the server for its StashDB descriptions, but
needs only Python 3 itself — no extra modules. It uses the StashDB
endpoint and API key you've set up under Settings → Metadata Providers.

For the **yt-dlp download** tool it also needs **yt-dlp** on the server:
`sudo apt install yt-dlp`, or `pip install yt-dlp` for the newest version.

Marker Improvements runs only in the browser and needs nothing extra.

Markers as Chapters needs only Python 3 — no extra modules; its online
chapters scraper also uses **yt-dlp** (see above).

## Features

### Scene Improvements

Formerly **Advanced File Operations**.

Adds **Convert to H265…**, **Split at Markers…** and **Repair File…** to
each scene's "⋮" operations menu, plus two library-wide conversion tasks
under Settings → Tasks.

- **Convert to H.265** at a chosen quality (presets or an exact CRF), per
  scene or for the whole library, skipping files that already are H.265.
- **Keep the original or replace it** — kept, the new file becomes the
  scene's primary file and the original stays attached as a secondary one.
- **Streams well in a browser**: index at the start of the file, clean
  seek points, and audio browsers can't play converted automatically.
- **Best audio option** for concerts and films: audio that has to be
  converted becomes lossless FLAC instead of AAC.
- **Split at markers**, either each marker as its own clip (start → end)
  or cutting the video at each marker — fast lossless cuts or
  frame-accurate ones.
- Split parts are named `.p1`, `.p2`, … with titles `#1`, `#2`, … and get
  the original's details, performers, tags, studio, URLs and markers.
- **Repair** finds decode errors and fixes them (lossless remux first,
  re-encode only if needed), and also fixes files that don't stream well.
- **Join recording parts** (VDR's `001.vdr`, `002.vdr` … / `00001.ts` …):
  one `.mkv` without re-encoding, made the scene's primary file, the parts'
  scenes moved into it with their markers shifted.
- New files are scanned with covers and phashes, and tasks are named
  after the scene with live progress.
- **Run in the background** (optional, per task): the work runs outside
  Stash's one-at-a-time task queue, so other tasks don't wait behind a
  long conversion; progress goes to a log file on the server.
- **Tools on Settings → Tools**, each a section of its own (Task history,
  Torrent check, Download):
  - **Torrent check**: which videos in a folder of `.torrent` files are
    already in your library — fuzzy matched by file name, with the
    certainty in %, sizes, resolution and codec side by side.
  - **Download with yt-dlp** into a library folder; the new scenes get
    title, source URL, upload date, description and cover filled in.
  - **Task history**: every finished task with status, duration and error
    — also under the running tasks on Settings → Tasks — with an ignore
    list for tasks you don't want in it.

Details: [Scene Improvements README](plugins/advanced-file-operations/README.md)

### Marker Improvements

- **Tag images on the seek bar**: a small bubble above each marker shows
  the images of its tags, appearing with Stash's own marker indicator.
- The same image is only shown once per marker, and images are never
  cropped.
- **Click to edit**: clicking a marker's icon or its range jumps there and
  opens Stash's edit marker dialog (can be switched off).
- **Hover a tag** in the marker form's dropdown, picked tags or the
  Markers tab's list to see its bubble.
- **Parent tags in the dropdown**: the marker form's tag dropdown shows
  each tag's parents, e.g. `Violin (Strings)`.
- **Custom styles per tag**: CSS rules by tag name, e.g.
  `Violin { outline: 2px solid gold }` — optionally matching parent tags
  too, so one rule for `Strings` styles all its sub-tags.
- **Custom styles per bubble**: the same rules for a marker's whole
  bubble, e.g. `Concerto { background: #ffe9b0 }`.
- **Marker list** in the Markers tab, in place of Stash's: each marker's
  screenshot and full details — click to jump, highlighted while playing,
  and editing opens right below the marker.
- **Stays up to date**: bubbles redraw by themselves after a marker is
  saved, added or deleted.

Details: [Marker Improvements README](plugins/marker-improvements-plugin/README.md)

### Markers as Chapters

- **Scrape markers…** next to Create Marker in the Markers tab imports
  markers the way Stash scrapes scenes — in sections: from the video and its
  files, from the scene's web pages, from text, tools. Entries that would
  find nothing for the scene are greyed out with the reason.
- **Sources**: chapters in the video file; a chapter file next to it (CUE,
  OGM, Matroska XML, ffmetadata, medici.tv / yt-dlp JSON, tracklist);
  chapters online (YouTube, ZDF … via yt-dlp); arte.tv / ARTE Concert; ORF
  ON; subtitles next to / in the video or online, and from OpenSubtitles (by
  the file's fingerprint); **text in the picture** (captions read with
  tesseract, as a Stash task); plain text — a tracklist, a table, a CUE
  sheet, JSON, a programme with or without times.
- **Checked against the audio**: the review dialog shows which markers
  start at a real pause, suggests a shift, snaps markers onto the pauses;
  titles without times are placed at the pauses between movements.
- **Chapters offered by themselves** when a scene without markers has some
  (a chapter file, the video's own, ARTE / ORF ON, subtitles made for the
  file).
- **Composers**: tags under **Composers** found in the titles (name, alias,
  surname) and the names taken out; missing composers imported from
  Wikidata; composers of scene (performer) and chapters (tag) kept in step.
- **Markers and the scene's files**: after merging scenes or changing the
  primary file, markers set on another file are lined up with the primary
  one — by the audio or by the picture, following cuts and PAL speed.
- **Copy as text** (tracklist, CUE, ffmetadata, JSON …) and **your own
  scrapers** as .yaml files in Stash's scraper format.

Details: [Markers as Chapters README](plugins/markers-as-chapters/README.md)

### Marker Editor for Chapters

- **The Markers tab as one table** of the scene's chapters (switch back to
  Stash's list any time), also as a dialog.
- **Add from every source** (Markers as Chapters' scrapers): a chapter at
  the same time gets it as an alternative — title, times or tags to take
  over — the rest come in as new chapters.
- **Combine duplicates**, **clean titles & composers**, **extend to the
  next pause**, **starts onto the pauses**, shift, a chapter at the player.
- **Overview bar** of the whole scene, columns to hide, **play statistics**
  per chapter, one **Save** for everything.

Details: [Marker Editor for Chapters README](plugins/marker-editor-for-chapters/README.md)

### Face Identifier

- **Learns your performers' faces** from their portraits (OpenCV's YuNet
  and SFace, on the Stash server).
- **⋮ → Who's in this scene?**: frames of the video looked at (as a Stash
  task); the recognised performers to add, the unknown faces to name —
  learnt for next time — and optionally **Visage**'s answer (StashDB /
  JavStash performers only).
- **Tagged scenes** task as starIdentifier: recognised performers added.

Details: [Face Identifier README](plugins/face-identifier/README.md)

### Tag Improvements

Formerly **Tag Tree**; it now also includes what was the separate **Scrape
Tag Merge** plugin.

- **All tags as a tree** of parents and sub-tags, as a **Tree** view on
  Stash's own Tags page (next to the usual cards) — optionally also from a
  button in the top navigation bar.
- Each tag with its **image**, a **link** to its page, and its **scene and
  marker counts**.
- **Search** by name or alias, with the path to every match opened.
- **Expand all / collapse all**, and the open branches are remembered.
- **Descriptions from StashDB** for every tag with a StashDB ID: right
  away for new or newly linked tags, every few days (adjustable), or on
  demand — a button for all tags and a ↻ per tag on the tree page.
- **Keeps your own text**: only empty descriptions and ones it wrote
  itself are replaced, unless you turn on "Overwrite".
- **Better tag search** in every tag field: every word, in any order, in a
  tag's name, aliases, description and parent tags; parent tags shown after
  each name; a switch in every tag dropdown makes it a full-height grid of
  tiles with images and descriptions.
- **Scrape with…** on a scene's Edit tab (a scraper or StashDB) offers the
  scene's **existing tags plus the scraped ones**, instead of replacing
  them.
- Tags can still be removed in the dialog before applying; unmatched
  scraped tags keep their create/link buttons.
- A setting switches back to Stash's usual replace behaviour.
- **Tags for composers and soloists** (**Performer roles**, e.g.
  `Composers: Composer; Soloists: Pianist, Violinist, …`): every performer
  with one of the roles — a performer tag (as the Classical Music scraper
  gives them) or the custom field `roles` — gets a tag of their own under
  the matching parent (name, aliases, image, details), kept in step when
  the performer is saved — so markers can carry composers and soloists.

Details: [Tag Improvements README](plugins/tag-improvements/README.md)

## License

[AGPL-3.0](LICENCE)
