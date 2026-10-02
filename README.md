# Stash classic music plugins

Plugins for [Stash](https://stashapp.cc), made for a library of concerts
and classical music recordings — but useful for any library.

| Plugin | What it's for |
|---|---|
| [Scene Improvements](plugins/advanced-file-operations/) | Convert to H.265, split a scene at its markers, repair a broken file; a torrent check and yt-dlp downloads |
| [Marker Improvements](plugins/marker-improvements-plugin/) | Tag images on the video's seek bar, click-to-edit markers |
| [Markers as Chapters](plugins/markers-as-chapters/) | Import chapters as markers: from the video file or a file next to it, YouTube, ARTE Concert, a pasted tracklist or programme — checked against the pauses in the audio |
| [Tag Improvements](plugins/tag-improvements/) | A tag tree on the Tags page, tag descriptions from StashDB, scraping that adds tags instead of replacing them, and composer tags kept in step with performers |

They're independent of each other — install any of them.

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
- New files are scanned with covers and phashes, and tasks are named
  after the scene with live progress.
- **Run in the background** (optional, per task): the work runs outside
  Stash's one-at-a-time task queue, so other tasks don't wait behind a
  long conversion; progress goes to a log file on the server.
- **Tools on Settings → Tools** (a Scene Improvements section):
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
  markers the way Stash scrapes scenes.
- **Built-in scrapers**: chapters in the video file; a chapter file next to
  it (CUE, OGM, Matroska XML, ffmetadata, yt-dlp info, tracklist); chapters
  online (YouTube, ZDF … via yt-dlp); arte.tv / ARTE Concert (one marker
  per work); ORF ON (its segments); plain text — paste a tracklist or pick a text/CUE file.
- **Checked against the audio**: the review dialog shows which markers
  start at a pause in the audio, suggests a shift when most would fit
  better, and snaps markers onto the pauses.
- **A programme without times** (ARD, BBC … list the pieces but no times):
  paste the titles, and they're placed at the pauses between movements.
- **Composers filled in**: tags under **Composers** are found in the
  titles — by name, alias or just the surname.
- **Review dialog**: pick, rename, tag, shift all times, then create.
- **Your own scrapers** as .yaml files in Stash's scraper format.

Details: [Markers as Chapters README](plugins/markers-as-chapters/README.md)

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
- **Composer tags**: every performer with a `composer` custom field gets a
  tag of their own under **Composers** (name, aliases, image, details),
  kept in step when the performer is saved — so markers can carry
  composers.

Details: [Tag Improvements README](plugins/tag-improvements/README.md)

## License

[AGPL-3.0](LICENCE)
