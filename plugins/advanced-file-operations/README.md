# Advanced File Operations (Stash plugin)

Three per-scene/library video tools in one plugin: convert to H.265,
split a scene at its markers, and repair a corrupt file. ffmpeg does all
the work; this plugin drives it from inside Stash and keeps Stash's
database in sync afterward.

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

## Converting a single scene from its page

Besides the two library-wide tasks, opening any scene now shows a
**Convert to H265** button. Click it to queue a conversion for just that
one file (it defaults to "replace original"; edit `keep_original` in
`h265-ui.js`'s `runConvertScene` call if you'd rather keep both files for
manual, one-off conversions too).

The button tries to slot itself into Stash's own toolbar. Since Stash's
internal page structure can differ by version, if you only ever see it as a
small floating button in the bottom-right corner instead of inline with
Stash's other scene buttons: open devtools on a scene page, find the
element wrapping Stash's own toolbar buttons, and add its CSS selector to
`TOOLBAR_SELECTORS` near the top of `h265-ui.js`. Either way, clicking it
works the same — it's purely cosmetic which container it ends up in.

## Splitting a scene at its markers

Every scene page also gets a **Split at Markers…** button. Clicking it
opens a small dialog listing every marker on the scene as a checkbox —
check the ones you want to cut at, leave the rest unchecked. Markers you
leave unchecked aren't lost: they're still carried over into whichever
part they land in, just not used as a cut point. The dialog also has
"keep original file" and "frame-accurate cuts" checkboxes (see below).

For each part it creates, the plugin:

- copies the title (suffixed `(part N)`), details, date, studio, performers,
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
- **Finding the new scenes.** After scanning, the plugin looks up each new
  file's scene by path to attach metadata and markers to it. Which
  GraphQL filter that lookup uses can vary a little by Stash version; it
  tries a direct path filter first and falls back to scanning your most
  recently created scenes if that's not available. If a part's log line
  says it "couldn't find the new scene," the file itself is still there
  and already scanned — you'll just need to add its title/performers/tags
  and markers by hand, or re-run a Scan and check again.

## Repairing a corrupt file

Every scene page also gets a **Repair File** button. It's safe to click on
anything — it always checks first, and if the file decodes cleanly it just
reports "nothing to repair" and stops there.

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
the original yourself. The scene gets tagged `File Repaired` either way
(so you can find everything the tool has touched later), and the checking
step decodes the entire file, so it can take a while on a long video.

## What it does

- Pages through every scene in your library.
- Skips a scene if its first video file already reports codec `hevc`/`h265`,
  or if the scene already carries the `H265 Converted` tag.
- Otherwise runs:
  ```
  ffmpeg -i <src> -c:v libx265 -preset slow -crf 18 -tag:v hvc1 \
         -pix_fmt yuv420p -c:a copy -c:s copy <output>
  ```
- On success, either overwrites the original file or writes
  `<name>.h265.mp4` alongside it (your choice of task), tags the scene
  `H265 Converted`, and triggers a rescan so Stash re-reads the new file's
  metadata.
- Logs a per-file error and moves on if a given file fails, rather than
  aborting the whole run.

## Tuning

Open `h265_transcode.py` and adjust the constants near the top:

| Constant | Effect |
|---|---|
| `CRF_VALUE` | Lower = closer to source quality, bigger files. 18 is a good "don't lose quality" target; try 20-22 if you want more compression and can tolerate a very slight softness. |
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
