# Marker Improvements (Stash plugin)

Puts each scene marker's tag images in a small bubble floating above
Stash's own colored marker indicator on the video scrubber — a real child
of that indicator, so it shows and hides right along with it, however
Stash itself reveals markers on the scrubber. Click an icon to jump
straight to that marker. Pure frontend — no Python, no ffmpeg, nothing to
configure server-side: the icons come straight from whatever images
you've already got on each tag in Stash. One optional setting lets you
restyle icons per tag (see "Custom styles per tag" below).

Source: https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/marker-improvements-plugin

## Install

1. Copy the whole `marker-improvements-plugin` folder into your Stash `plugins`
   directory (same place as any other plugin — Settings → Plugins shows
   the exact path).
2. Settings → Plugins → **Reload plugins**.
3. Open any scene with markers and look at the colored marker indicators
   on the scrubber.

## Icons

Each marker shows one icon per tag on it that actually has an image
uploaded — the one you can upload from that tag's page in Stash — not
just its primary tag. If a marker has three tags and two of them have
images, you get two icons clustered together at that marker's position;
hover each one (title tooltip) to see which tag it is. A marker where
none of its tags have an image (or it has no tags at all) gets no icon at
all — there's no generic placeholder pin. If one particular tag's image
URL fails to load, just that one icon is dropped — its other tag icons
are unaffected.

## Custom styles per tag

Settings → Plugins → Marker Improvements → **Custom styles per tag**
takes extra CSS for tag icons, written like CSS rules with tag names in
place of selectors:

```
Violin { outline: 2px solid gold }
Piano, Cello { opacity: .6 }
* { filter: grayscale(1) }
```

- Each rule's CSS goes on that tag's icon; list several tags in one rule
  by separating them with commas.
- A rule matches every tag whose name *contains* its text, ignoring
  case — `Violin` also styles "Violin I" and "Solo Violin".
- `*` applies to every icon. It goes on first, then the other rules in
  the order written, so a later rule wins where two match the same icon
  and set the same property.
- These are applied last, so they override the icon's built-in look too
  (e.g. `Violin { border: 2px solid gold }` replaces its thin grey border).
- Line breaks are optional — the whole thing can be on one line.

Changes apply the next time a scene page loads.

## Where the symbols show up

Directly inside Stash's own colored marker indicator for that marker —
the small tinted bar (class `.vjs-marker-range`) Stash itself draws on
the scrubber at each marker's timestamp. The bubble is an actual child of
that element (not a separate overlay layered on top), floats centered
above it with a small tail pointing back down at it.

A `.vjs-marker-range` element is usually only a few px tall, and can clip
its own content (`overflow: hidden`) for a rounded-track look — which
would otherwise cut a 22px icon down to an invisible sliver. Rather than
avoiding that by rendering somewhere else, this forces
`overflow: visible` on it and any clipping ancestor up to the player
(restored on navigating away), so the icon genuinely lives inside that
bar and just pokes slightly above/below its thin box.

A `.vjs-marker-range` is also often styled `pointer-events: none` by the
player, so it doesn't interfere with dragging the real seek handle
underneath it. That's left untouched — the icon group sets its own
`pointer-events: auto` explicitly instead (a CSS-inherited property, so
that takes over for the icon's own subtree regardless of what the
indicator itself is set to), so clicking an icon still works without
having to change how the indicator itself handles clicks anywhere else on
its own area.

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

## If an icon disappears after clicking it

Clicking an icon seeks the video to that marker's timestamp. Since
`.vjs-marker-range` is a React-managed element that knows nothing about
the icon manually injected into it, Stash re-rendering its marker overlay
in response to that seek (e.g. to update which marker is "active") can
wipe the icon out as a side effect — not because this plugin removed it.
A `seeked` listener on the video watches for exactly that and re-mounts
automatically whenever an icon has actually gone missing from the DOM, so
this should self-heal within a moment; if it doesn't, that's worth
reporting.

## Diagnostics

Every time markers are placed, the console logs a table
(`[Marker Symbols] Paired N marker(s) to .vjs-marker-range element(s)...`)
showing, for each pairing: the marker, that `.vjs-marker-range`'s measured
position, its class, its `pointer-events` value, and whether an icon was
actually built for it. Useful for checking the left-to-right pairing
itself is landing where expected, or whether a marker was skipped because
none of its tags have a real custom image.

## Notes

- This only reads markers/tags — it never creates, edits, or deletes
  anything in Stash.
- If a scene has a lot of markers close together, their icons can overlap
  a bit on the scrubber; that's a display-only trade-off, nothing is lost
  or hidden from the underlying data.
- Icon size is controlled by `ICON_SIZE_PX` near the top of the script if
  you want them bigger or smaller.
