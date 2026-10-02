# Scene Improvements (Stash plugin)

*Formerly called **Advanced File Operations**.*

Three per-scene/library video tools in one plugin: convert to H.265,
split a scene at its markers, and repair a corrupt file. ffmpeg does all
the work; this plugin drives it from inside Stash and keeps Stash's
database in sync afterward.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/advanced-file-operations

## Install

1. Copy the whole `advanced-file-operations` folder into your Stash `plugins`
   directory (Settings → Plugins shows you the exact path — usually
   `~/.stash/plugins/`).
2. Make sure `ffmpeg`/`ffprobe` (built with `libx265`) are available to the
   process Stash runs as. If you're unsure, run `ffmpeg -version` in the same
   environment Stash starts from and check for `--enable-libx265`.
3. Install the one Python dependency:
   ```
   pip install -r requirements.txt
   ```
   (into whichever Python `python` resolves to for Stash's plugin exec).
4. In Stash: Settings → Plugins → **Reload plugins**.
5. Settings → Tasks → you'll see two new tasks under "Plugin Tasks":
   - **Convert Library to H265 (replace originals)**
   - **Convert Library to H265 (keep originals)**

Run either one. Progress and a running log show up in the task UI.

## The scene menu

Besides the two library-wide tasks, every scene's "⋮" operations menu
(the one with Stash's own Rescan, Generate, Delete, …) gets three more
entries below a divider: **Convert to H265…**, **Split at Markers…**, and
**Repair File…** — described individually below.

If your Stash version has no such menu, a small **File Operations**
button (scissors icon) shows up in the scene toolbar instead, with the
same three actions. If even that can't find Stash's toolbar, it floats
in the bottom-right corner; to fix that, open devtools on a scene page,
find the element wrapping Stash's own toolbar buttons, and add its CSS
selector to `TOOLBAR_SELECTORS` near the top of `h265-ui.js`.

If starting a task fails, a message box says why (the full error is in
the browser console).

## Converting a single scene from its page

Choose **Convert to H265…** from the scene's ⋮ menu. A dialog opens
first, letting you pick:

- **Quality** — a preset (Highest / Visually lossless / Balanced / Smaller
  / Smallest, each mapping to an x265 CRF value) or **Custom CRF…** to type
  an exact 0-51 value.
- **Best audio** — for concerts and films where the sound matters.
  Audio a browser can already play from an .mp4 (AAC, MP3, FLAC) is
  always copied untouched; anything else (AC3, DTS, PCM, …) has to be
  converted, normally to AAC at 192 kbit/s. Tick this to convert it to
  lossless FLAC instead — still playable in current Chrome, Firefox,
  Edge and Safari, but bigger. Audio that was already lossy (AC3, DTS)
  comes out exactly as it was; FLAC just stops it losing anything more.
- **Keep original file** — checked by default. With it checked, the
  original is never deleted: the new H265 file is written alongside it,
  attached to the *same* scene, and set as that scene's primary file —
  everything else (title, tags, performers, markers, O-counter, rating,
  galleries) stays put since it's still the same scene, just with a
  different file now used for playback. Unchecking it goes back to the
  old "replace" behavior: the original is overwritten in place and gone
  for good.

The item is greyed out ("already H265") if the scene's file already reports
codec `hevc`/`h265`/`x265`, or already carries the `H265 Converted` tag —
there's nothing for it to do in that case. (This is a client-side
shortcut for convenience; the task itself re-checks the same thing
server-side regardless.)

Attaching the new file happens in a second task. Stash runs one task at
a time, so the conversion can't wait for its own scan of the new file:
it converts, queues a scan, and queues **Finish converting "…"** behind
it, which attaches the file once the scan has picked it up. Until that
has run, the new file briefly shows up as its own bare scene. The same
happens when *replacing* a file that wasn't already `.mp4` — the result
is a new `.mp4` at a new path, which Stash would otherwise treat as a
brand-new scene. (The original file then stays listed on the scene as
missing until Stash's own **Clean** task removes it.) The library-wide
tasks queue one scan and one **Finish converting library** task for the
whole run, not one per scene.

If the automatic "set as primary" linking ever fails (an older Stash
version without multi-file-scene support, a schema mismatch, etc.), the
task log says so explicitly — the converted file is always safely on disk
and already scanned into Stash by that point, it just needs one manual
"Set as primary" click in the scene's Files tab instead of happening on
its own.

## Tools on Settings → Tools

Stash's own **Settings → Tools** page gets a **Scene Improvements**
section with three tabs: **Torrent check**, **Download (yt-dlp)** and
**Task history**. (The older address `/plugin/file-tools` still shows the
same tools as a page of their own.)

### Torrent check

Which videos in your `.torrent` files (also `.torrent.added`) do you
already have? Enter one or more folders, separated by `;`
on the server with `.torrent` files (or set a default with the **Torrent
folder** setting) and **Run check**. The table lists every video in every
torrent next to its best-matching scene:

| Column | |
|---|---|
| Match | how certain it's the same video, in %, and the verdict: **In library** (85 % and up), **Possible match** (60 %+) or **Not found** |
| Torrent / file | the video's path inside the torrent, and the torrent file |
| Size | the video's size |
| Res. / codec | resolution and codec — guessed from the name ("1080p", "x265"), since a .torrent file only has names and sizes |
| Scene, size, res. / codec | the matching scene (a link) with its file's real size, resolution and codec |

Filter by verdict with the drop-down; the best matches come first.

How it matches: both file names are reduced to their words, leaving out
release tags that say nothing about the content (1080p, x265, WEB-DL,
DDP5.1, …). The score combines how similar the names are with how many of
the torrent file's words the library name has. **Numbers decide**:
"Symphony No. 5" and "Symphony No. 7" never match, however alike the rest
is. **An identical file size** counts as the same file, whatever it's
called now. Sample clips inside a torrent are skipped; torrent files that
can't be read are listed under the table. Each torrent has a **Delete torrent**
button that deletes just that `.torrent` file (after asking) — only files
inside the folders being checked. Opening the tab runs the check right
away for the folders you used last, or the **Torrent folder** setting's.

The check runs right away (not as a task), reading your whole library's
file list once, so it takes a few seconds on a large library.

### Download (yt-dlp)

Download videos — or whole playlists — with [yt-dlp](https://github.com/yt-dlp/yt-dlp)
straight into one of your library folders: paste URLs (one per line),
pick the folder, an optional subfolder and the quality, and **Download**.
Progress shows in Settings → Tasks; tick **Run in the background** to keep
the task queue free. Your last folder, subfolder and quality are
remembered.

Needs **yt-dlp** on the server: `sudo apt install yt-dlp`, or
`pip install yt-dlp` for the newest version (sites change often; an old
yt-dlp is the most common reason a download fails).

#### What happens after the download

Stash runs one task at a time, so the download can't wait for its own
scan. Instead it queues a scan of the new files and a **Finish downloads**
task behind it. That one runs once the scan has created the scenes, and
fills each one in:

| Scene field | From |
|---|---|
| Title | the video's title |
| URL | the video's canonical page — or, when the site doesn't report one, the URL you pasted |
| Date | its release or upload date |
| Details | its description |
| Cover | its thumbnail |

The video's chapters (YouTube, ZDF …), if it has any, are saved in the
file, so Markers as Chapters' **Video file chapters** scraper can turn
them into markers.

Until it has run, the new scenes show up with just their file name. The
video information and thumbnails are kept in a temporary folder, not in
your library (so Stash doesn't import the thumbnails as images), and
deleted once the scenes are filled in.

### Running in the background

Tick **Run in the background** in the dialog and the download runs
outside Stash's one-at-a-time task queue, so other tasks don't wait
behind it. The task finishes at once and names a log file (in a `logs`
folder inside the plugin's folder) with the download's progress, and the
command to stop it (`kill -- -<pid>`). The scan and **Finish downloads**
are queued as usual when it's done.

### Settings

Settings → Plugins → Scene Improvements:

| Setting | Effect |
|---|---|
| Path to yt-dlp | Leave empty if `yt-dlp` is on the server's PATH; otherwise its full path. |
| Cookies file | A `cookies.txt` on the server, for sites that need a login. |
| Extra yt-dlp options | Passed to yt-dlp as they are, e.g. `--limit-rate 5M --embed-subs`. |

### Requirements

- **yt-dlp** on the machine Stash runs on — Debian/Ubuntu:
  `sudo apt install yt-dlp`, or `pip install yt-dlp` for the newest
  version (sites change often; an old yt-dlp is the most common reason a
  download fails).
- **ffmpeg**, for merging video and audio — Stash needs it anyway.
- **Python 3** — standard library only, nothing else to install.
- The library folder you save into must be one of Stash's library paths
  (Settings → Library); the dialog only offers those.


Only download what you have the right to.

#### Coming from the separate "yt-dlp Downloader" plugin

That plugin is now part of Scene Improvements. Uninstall it
(Settings → Plugins); its settings (path to yt-dlp, cookies file, extra
options) need setting again here.

### Task history

Stash keeps no history of finished tasks — its task list only shows what's
queued or running. This plugin records every task as it finishes and
shows the history as **Task History right underneath the Job Queue on
Settings → Tasks** — drawn just like the queue, one entry per task with
its status icon, description, when it ended and how long it took, and
the error for failed ones — and as the **Task history** tab on Settings → Tools. Filter
by status, remove single entries with their **×**, or clear it.

- Tasks are recorded while any Stash page is open. Stash still remembers
  its last 10 finished tasks, so ones that finished while no page was open
  are picked up the next time one is — as long as they're among those 10.
- The history is kept on the server (`task-history.json` in the plugin's
  folder), so every browser and device shows the same list; the newest
  500 tasks are kept.
- **Task history: ignore** (Settings → Plugins → Advanced File
  Operations) leaves tasks out, separated by commas: a name without `*`
  matches every task whose description contains it, with `*` it's a
  pattern for the whole description — e.g. `Scan*, Generate*, (automatic)`.
  Ignored tasks aren't recorded, and ones recorded before are hidden.
- If a Stash version builds the Tasks page differently, the history just
  doesn't show there; this tab always has it.

## Splitting a scene at its markers

Choose **Split at Markers…** from the scene's ⋮ menu. It opens a
small dialog listing every marker on the scene as a checkbox, with two
modes to choose from:

- **Each marker as its own clip (start → end)** — the default. Every
  checked marker becomes its own new scene, cut from where the marker
  starts to where it ends. A marker without an end time (or on a Stash
  older than v0.27, which has no marker end times) runs until the next
  marker, or to the end of the video if it's the last one — those are
  shown with a `*` in the list. Parts of the video outside every checked
  marker don't end up in any new file.
- **Cut the video at each marker** — the file is cut at every checked
  marker, so the parts together cover the whole video. Markers you leave
  unchecked aren't lost: they're still carried over into whichever part
  they land in, just not used as a cut point.

The dialog also has "keep original file" and "frame-accurate cuts"
checkboxes (see below).

For each part it creates, the plugin:

- copies the title (suffixed ` #N`, matching the `.pN` in the part's filename), details, date, studio, performers,
  tags, URLs and StashDB IDs from the original scene
- re-creates whichever of the original scene's markers fall inside that
  part, with their timestamps shifted to be relative to that part's start

Every part gets the *same* URLs/StashDB IDs as the original — that's the
straightforward option, and correct if the original scene's URL points at
a compilation and every part is legitimately "from" it. If your source
URLs are actually per-scene (a multi-scene release where each part has its
own distinct page), you'll want to fix those up by hand afterward, since
the plugin has no way to know which URL goes with which time range.

Not copied at all: rating, cover image, O-counter, and any galleries or
groups/movies the original is linked to.

Two things worth knowing:

- **Cut precision.** With "frame-accurate cuts" left unchecked (the
  default), cuts stream-copy — no re-encoding, no quality loss — but snap
  to the nearest keyframe, so a part can start up to a second or two
  before/after the exact marker you picked. Checking "frame-accurate cuts"
  re-encodes each part so the cut lands exactly on the marker, at the cost
  of re-encode time and a second generation of lossy compression.
- **Two tasks, not one.** Stash runs one task at a time, so the split
  can't wait for its own scan of the new files — the scan wouldn't start
  until the split ended. Instead the split cuts the files, queues a scan,
  and queues a second task, **Finish splitting "…"**, behind it. That one
  runs once the scan is done and copies the details and markers onto the
  new scenes. Until it has run, the new scenes show up bare.
- **Finding the new scenes.** After scanning, the plugin looks up each new
  file's scene by path to attach metadata and markers to it. Which
  GraphQL filter that lookup uses can vary a little by Stash version; it
  tries a direct path filter first and falls back to scanning your most
  recently created scenes if that's not available. If a part's log line
  says it "couldn't find the new scene," the file itself is still there
  and already scanned — you'll just need to add its title/performers/tags
  and markers by hand, or re-run a Scan and check again.

## Running in the background

Stash runs one task at a time, so a long conversion — hours for a film on
a small server — holds up everything else in the queue, scans included.
The Convert, Split and Repair dialogs each have a **Run in the background**
checkbox (off by default). With it ticked:

- The Stash task only starts the work as a separate process on the server
  and finishes within seconds (its name ends in "(started in
  background)"), so the queue is free for other tasks at once.
- The background process does the work, then queues the scan and the
  **Finish …** task in Stash as usual, so new files still end up on the
  right scenes.
- Its messages and progress (in 5% steps) go to a log file in a `logs`
  folder inside the plugin's folder (or the system temp folder if that
  isn't writable), named like
  `afo-20260929-085612-convert_scene-scene7.log`. The Stash task's result
  shows the exact path. Logs older than 30 days are deleted when a new
  background run starts.
- There's no progress bar or cancel button in Stash. To stop it, run the
  command the task's result shows on the server — `kill -- -<pid>`, which
  stops the process and its ffmpeg together.

Two things to know:

- Several background runs at once work, but don't finish sooner in total:
  x265 already uses every CPU core for one file.
- If your Stash requires a login, the background process uses the login
  session the task started with. A run that takes longer than Stash's
  session lifetime can fail at the very end, when it queues the scan —
  the new file is still on disk; scan it in by hand. Setting an API key in
  the environment Stash runs in (`STASH_API_KEY`) avoids this.

## Repairing a corrupt file

Choose **Repair File…** from the scene's ⋮ menu. A small dialog
asks two things first:

- **What happens to the original** — either the repaired file is
  *attached* to the scene as its primary file, with the original kept on
  the scene as a secondary file (the default — nothing is deleted), or it
  *replaces* the original, which is deleted.
- **Best audio** — same as in the Convert dialog: audio a browser can't
  play becomes lossless FLAC instead of AAC.

It's safe to run on anything — it always checks first, and if the file decodes cleanly
*and* streams well it just reports "nothing to do" and stops there.

**Streaming fix.** A file that decodes cleanly can still play badly in a
browser. Repair also looks for three things a lossless remux fixes: the
index (moov atom) sitting at the end of an .mp4, so the browser has to
fetch the end before it can play or seek; audio browsers can't play from
an .mp4 (AC3, DTS, PCM, … — re-encoded to AAC; the video itself is copied
untouched); and a container browsers can't play directly
(.mkv, .avi, …), remuxed into .mp4. It also retags H.265 video marked
`hev1` as `hvc1`: Safari and Apple devices only play H.265 from an .mp4
tagged `hvc1`, and fall back to Stash's live transcoding otherwise. That
only helps Safari, iPhone, iPad and Mac — Firefox, and Chrome without
hardware H.265 decoding, can't play H.265 at all, whatever the tag. If the video codec itself doesn't fit
in an .mp4, it says so and stops rather than re-encoding a healthy file —
use Convert to H265 for that.

If it finds decode errors, it tries two things in order:

1. **Lossless remux** — repackages every stream as-is into a fresh,
   cleanly-indexed file. This alone fixes most "won't seek", "wrong
   duration", "moov atom not found" style problems, which are almost
   always container/index damage rather than the actual video data being
   bad — so most repairs cost you nothing in quality.
2. **Tolerant re-encode** — only if the remux still isn't clean, meaning
   the damage is in the stream data itself. This re-decodes and
   re-encodes while skipping corrupt packets, recovering everything that's
   actually readable. It's lossy (a second generation of compression), and
   there's an honest limit here: no repair tool can reconstruct video data
   that's truly gone — a bad stretch comes out as a skip or a glitch, not
   restored footage.

By default the repaired file is written as `<name>.repaired.mp4` next to
the original, which is left untouched — check playback before deleting
the original yourself. Like a conversion, a queued **Finish repairing
"…"** task attaches the repaired file to the same scene as its primary
file once the scan has picked it up, with the original kept on the scene
as a secondary file. The scene gets tagged `File Repaired` either way
(so you can find everything the tool has touched later), and the checking
step decodes the entire file, so it can take a while on a long video.

## What it does

- Pages through every scene in your library (or just the one scene, for a
  per-scene conversion).
- Skips a scene if its first video file already reports codec `hevc`/`h265`,
  or if the scene already carries the `H265 Converted` tag.
- Otherwise runs (CRF 18 shown; the actual value depends on the quality
  you picked, or `CRF_VALUE` below for the library-wide tasks, which have
  no per-run quality picker):
  ```
  ffmpeg -i <src> -c:v libx265 -preset slow -crf 18 -tag:v hvc1 \
         -pix_fmt yuv420p -c:a copy -c:s copy <output>
  ```
- On success, tags the scene `H265 Converted`, then either:
  - **replaces the original** (overwrites it in place), or
  - **keeps the original**: writes `<name>.h265.mp4` alongside it, scans
    it in, attaches it to the same scene, and sets it as that scene's
    primary file — the original stays on the scene as a secondary file,
    never deleted.
- Logs a per-file error and moves on if a given file fails, rather than
  aborting the whole run.

## Tuning

For a one-off scene, quality is a menu away — no editing needed (see
above). For everything else, open `h265_transcode.py` and adjust the
constants near the top:

| Constant | Effect |
|---|---|
| `CRF_VALUE` | Default CRF used by the library-wide Settings > Tasks entries (which have no per-run quality picker) and as the fallback if a `quality`/`crf` arg is missing or invalid. 18 is a good "don't lose quality" target; try 20-22 if you want more compression and can tolerate a very slight softness. |
| `QUALITY_PRESETS` | The named presets offered in the "Convert to H265…" dialog's quality dropdown. Add, remove, or re-tune entries here — just keep the `QUALITY_OPTIONS` list in `h265-ui.js` in sync with the keys. |
| `X265_PRESET` | Slower presets (`slow`, `veryslow`) squeeze more quality out of the same CRF but take longer. `medium` is faster if your hardware is the bottleneck. |
| `DONE_TAG_NAME` | Change the marker tag name if you want something else. |

## Honest note on "without losing quality"

H.265 is a lossy codec — converting into it always re-derives the picture
from scratch, so there's no setting that makes it byte-for-byte identical to
the source. CRF 18 is what the encoding community generally calls "visually
lossless": in blind tests, most people can't tell it apart from the
original, and it's noticeably smaller than an H.264 file at a comparable
visual quality. If you truly need bit-exact preservation, keep the
originals (use the "keep originals" task) rather than relying on any lossy
re-encode.

## Uninstall

Delete the plugin folder and reload plugins. Already-converted files and
the `H265 Converted` tag are left as-is.
