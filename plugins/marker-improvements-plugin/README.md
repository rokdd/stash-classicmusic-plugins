# Marker Improvements (Stash plugin)

Puts each scene marker's tag images on the video scrubber, at that
marker's exact timestamp, hidden until you hover, drag, touch, or
keyboard-focus the scrubber. Click an icon to jump straight to that
marker. Pure frontend — no Python, no ffmpeg, nothing to configure
server-side or in a settings dialog: the icons come straight from
whatever images you've already got on each tag in Stash.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/marker-improvements-plugin

## Install

1. Copy the whole `marker-improvements-plugin` folder into your Stash `plugins`
   directory (same place as any other plugin — Settings → Plugins shows
   the exact path).
2. Settings → Plugins → **Reload plugins**.
3. Open any scene with markers and hover (or drag/touch) the scrubber.

## Icons

Each marker shows one icon per tag on it that actually has an image
uploaded — the one you can upload from that tag's page in Stash — not
just its primary tag. If a marker has three tags and two of them have
images, you get two icons clustered together at that marker's position;
hover each one to see which tag it is. A marker where none of its tags
have an image (or it has no tags at all) gets no icon at all — there's no
generic placeholder pin. If one particular tag's image URL fails to load,
just that one icon is dropped — its other tag icons are unaffected.

## Hidden until the scrubber is in use

The icons are invisible during normal playback and appear when the
scrubber is:

- **hovered** — mouse enters it,
- **actively dragged** — mouse/touch held down, even if the drag continues
  past the edge of the bar itself,
- **touched** — touch devices have no hover state at all, so this is what
  makes the icons reachable on mobile, or
- **keyboard-focused** — tabbing to it.

They fade back out once none of those are true anymore. While hidden,
they also don't intercept clicks, so the icons being gone doesn't change
how seeking on the bar behaves.

## Where the symbols show up

Directly inside the real video scrubber — the icons are appended as
actual children of it, positioned proportionally along it by each
marker's timestamp, not a separate element merely layered on top. Which
exact element counts as "the scrubber" varies a little by Stash version,
so this tries a short list of known selectors first; if none of them
match yours, it falls back to drawing its own thin hover-reveal bar
directly under the video instead (still clickable, still correctly
positioned, just not part of Stash's own control bar).

If you get the fallback bar and want it merged into your actual scrubber:
open devtools on a scene page, click into the seek bar's element in the
inspector to find the right container, and add its CSS selector to
`SCRUBBER_SELECTORS` near the top of `marker-symbols.js`. The console logs
which one it's using (`[Marker Symbols] Rendering directly on the real
scrubber` or a warning about the fallback), so you can check that instead
of guessing from what you see on screen.

The real scrubber's own track is usually only a few px tall, and some
themes clip its content (`overflow: hidden`) for a rounded-track look —
which would otherwise cut a 22px icon down to an invisible sliver. Rather
than avoiding that by rendering somewhere else, this forces
`overflow: visible` on the scrubber and any clipping ancestor up to the
player (restored on navigating away), so the icons genuinely live inside
the seek bar and just poke slightly above/below its own thin box.

### Mounted onto Stash's own colored marker indicators

Stash draws its own small colored marker indicator per marker on the
scrubber (class `.vjs-marker-range`, a thin tinted bar positioned at its
timestamp). Each tag icon is mounted directly inside the matching
indicator — matched by comparing positions, since both are computed from
the same seconds/duration math — and its border/glow is tinted to that
indicator's own color, so it reads as part of the colored bar rather than
something dropped on top of it. A marker whose indicator can't be matched
(or on a player version that doesn't draw these at all, or if the class
name changes in a future Stash version) still gets its icon positioned by
percentage along the scrubber as before, so nothing's ever silently
dropped — update `NATIVE_MARKER_SELECTORS` near the top of
`marker-symbols.js` if that ever happens. The console line says how many
it found: `(N/M icon(s) mounted onto Stash's own .vjs-marker-range
indicators)`.

## Notes

- This only reads markers/tags — it never creates, edits, or deletes
  anything in Stash.
- If a scene has a lot of markers close together, their icons can overlap
  a bit on the scrubber; that's a display-only trade-off, nothing is lost
  or hidden from the underlying data.
- Icon size is controlled by `ICON_SIZE_PX` near the top of the script if
  you want them bigger or smaller.
