# Marker Improvements (Stash plugin)

Puts each scene marker's tag images directly inside Stash's own colored
marker indicator on the video scrubber, hidden until you hover, drag,
touch, or keyboard-focus that specific indicator. Click an icon to jump
straight to that marker. Pure frontend — no Python, no ffmpeg, nothing to
configure server-side or in a settings dialog: the icons come straight
from whatever images you've already got on each tag in Stash.

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/marker-improvements-plugin

## Install

1. Copy the whole `marker-improvements-plugin` folder into your Stash `plugins`
   directory (same place as any other plugin — Settings → Plugins shows
   the exact path).
2. Settings → Plugins → **Reload plugins**.
3. Open any scene with markers and hover (or drag/touch) one of the
   colored marker indicators on the scrubber.

## Icons

Each marker shows one icon per tag on it that actually has an image
uploaded — the one you can upload from that tag's page in Stash — not
just its primary tag. If a marker has three tags and two of them have
images, you get two icons clustered together at that marker's position;
hover each one to see which tag it is. A marker where none of its tags
have an image (or it has no tags at all) gets no icon at all — there's no
generic placeholder pin. If one particular tag's image URL fails to load,
just that one icon is dropped — its other tag icons are unaffected.

## Where the symbols show up

Directly inside Stash's own colored marker indicator for that marker —
the small tinted bar (class `.vjs-marker-range`) Stash itself draws on
the scrubber at each marker's timestamp. The icon is an actual child of
that element, not a separate overlay layered on top, and its border/glow
is tinted to match that indicator's own color so it reads as part of the
colored bar.

A `.vjs-marker-range` element is usually only a few px tall, and can clip
its own content (`overflow: hidden`) for a rounded-track look — which
would otherwise cut a 22px icon down to an invisible sliver. Rather than
avoiding that by rendering somewhere else, this forces
`overflow: visible` on it and any clipping ancestor up to the player
(restored on navigating away), so the icon genuinely lives inside that
bar and just pokes slightly above/below its thin box.

### How markers are matched to their indicator

Stash doesn't expose which `.vjs-marker-range` belongs to which marker by
id or attribute, so this pairs them up by left-to-right order: every
`.vjs-marker-range` found, sorted by its own position along the bar,
against every marker from GraphQL, sorted by timestamp — index 0 of one
with index 0 of the other, and so on. Both lists are normally in the same
order and the same length once the player's finished setting up, so this
works reliably in practice.

If the counts don't match — the player hasn't drawn its marker ranges yet
when this first runs, or a future Stash version changes how these are
exposed — the console warns about it and only pairs up the matching
prefix; the plugin also waits and retries (up to 20 times, 500ms apart)
if it finds zero `.vjs-marker-range` elements at all rather than giving
up immediately. If Stash ever renames the class, update
`MARKER_RANGE_SELECTOR` near the top of `marker-symbols.js`.

## Hidden until that marker's indicator is in use

Each icon is invisible during normal playback and appears when its own
`.vjs-marker-range` is:

- **hovered** — mouse enters it,
- **actively dragged** — mouse/touch held down, even if the drag continues
  past its edge,
- **touched** — touch devices have no hover state at all, so this is what
  makes the icon reachable on mobile, or
- **keyboard-focused** — tabbing to it.

It fades back out once none of those are true anymore for that
indicator. While hidden, it also doesn't intercept clicks, so the icon
being gone doesn't change how seeking on the bar behaves.

## Diagnostics

Every time markers are placed, the console logs a table
(`[Marker Symbols] Tag image plan — ...`) of every marker's tags and
whether each one qualifies for an icon — check that against what actually
renders if something looks off (a tag showing `false` there has no real
custom image, so it's correctly excluded, not a bug). A second line says
how many `.vjs-marker-range` elements were found vs. how many markers
came back from Stash, and how many icons actually got mounted.

## Notes

- This only reads markers/tags — it never creates, edits, or deletes
  anything in Stash.
- If a scene has a lot of markers close together, their icons can overlap
  a bit on the scrubber; that's a display-only trade-off, nothing is lost
  or hidden from the underlying data.
- Icon size is controlled by `ICON_SIZE_PX` near the top of the script if
  you want them bigger or smaller.
