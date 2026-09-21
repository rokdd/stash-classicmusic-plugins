# Marker Improvements (Stash plugin)

Puts each scene marker's tag image on the video scrubber, at that marker's
exact timestamp, hidden until you hover the scrubber. Click an icon to
jump straight to that marker. Pure frontend — no Python, no ffmpeg,
nothing to configure server-side or in a settings dialog: the icons come
straight from whatever image you've already got on each tag in Stash.

## Install

1. Copy the whole `marker-improvements-plugin` folder into your Stash `plugins`
   directory (same place as any other plugin — Settings → Plugins shows
   the exact path).
2. Settings → Plugins → **Reload plugins**.
3. Open any scene with markers and hover the scrubber.

## Icons

Each marker's icon is its primary tag's own image — the one you can
upload from that tag's page in Stash. A marker whose tag has no image
(or has no primary tag at all) gets a small default 📍 instead of nothing.
If a tag's image URL fails to load for some reason, it falls back to that
same default pin rather than showing a broken-image icon.

## Hover to reveal

The icons are invisible until your mouse enters the scrubber, and fade
back out when it leaves — this is deliberate, so they don't clutter the
player during normal playback. While hidden, they also don't intercept
clicks, so hovering away doesn't change how seeking on the bar behaves.

## Where the symbols show up

On the real video scrubber, positioned proportionally along it by each
marker's timestamp. Which exact element counts as "the scrubber" varies a
little by Stash version, so this tries a short list of known selectors
first; if none of them match yours, it falls back to drawing its own thin
hover-reveal bar directly under the video instead (still clickable, still
correctly positioned, just not pixel-perfect over Stash's own control
bar).

If you get the fallback bar and want it merged into your actual scrubber:
open devtools on a scene page, click into the seek bar's element in the
inspector to find the right container, and add its CSS selector to
`SCRUBBER_SELECTORS` near the top of `marker-symbols.js`.

## Notes

- This only reads markers/tags — it never creates, edits, or deletes
  anything in Stash.
- If a scene has a lot of markers close together, their icons can overlap
  a bit on the scrubber; that's a display-only trade-off, nothing is lost
  or hidden from the underlying data.
- Icon size is controlled by `ICON_SIZE_PX` near the top of the script if
  you want them bigger or smaller.
