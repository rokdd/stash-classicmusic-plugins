# Marker Improvements (Stash plugin)

Puts each scene marker's tag images in a small bubble floating above
Stash's own colored marker indicator on the video's seek bar — a real child
of that indicator, so it shows and hides right along with it, however
Stash itself reveals markers on the seek bar. Click an icon to jump
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
   on the seek bar.

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

## When bubbles show, and where

- **Only once the video has started**: before you first press play, the
  seek bar shows no bubbles. They appear when playback starts, and hide
  again when a new video loads.
- **At the start of the marker's range**: each bubble sits with its left
  edge at where its marker begins, its tail pointing at that spot.
- **Out of the way of the seek preview**: while you hover the seek bar
  itself, the bubbles fade away so Stash's preview frame shows; moving up
  off the bar brings them back.
- **Never on top of each other**: when markers sit close together, their
  bubbles stack upwards in rows instead of overlapping. A raised bubble
  gets a thin line down to its marker. The rows are worked out again
  whenever sizes change — images loading, the player resizing.

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
- **Wildcards:** a name with a `*` in it is a pattern for the *whole* tag
  name, `*` standing for any text — `Solo*` matches names starting with
  "Solo" (Solo Violin, not Violin Solo), `*Concerto` names ending with
  "Concerto", `Concerto*Piano` names that start with one and end with the
  other. Names without a `*` keep matching anywhere in the name.
- `*` applies to every icon. It goes on first, then the other rules in
  the order written, so a later rule wins where two match the same icon
  and set the same property.
- These are applied last, so they override the icon's built-in look too
  (e.g. `Violin { border: 2px solid gold }` replaces its thin grey border).
- Line breaks are optional — the whole thing can be on one line.

**Styling the whole bubble.** Settings → Plugins → Marker Improvements →
**Custom styles per bubble** takes rules in exactly the same format, but
their CSS goes on a marker's whole bubble instead of one icon. A rule
applies when *any* of the marker's tags contains its text — including
tags without an image, so a category tag can color a bubble without
adding an icon of its own:

```
Concerto { background: #ffe9b0; border: 2px solid #c90 }
* { padding: 4px 6px }
```

The little tail under the bubble takes on the bubble's background, so a
custom background covers both. Bubbles are aligned to the start of their
marker's range; to make one bigger without it drifting away from there,
scale it from its bottom-left corner:
`transform: scale(1.2); transform-origin: left bottom`.

**Matching parent tags too.** Turn on Settings → Plugins → Marker
Improvements → **Custom styles also match parent tags**, and a rule in
either style setting also
applies to a tag when any tag above it in the hierarchy — its parents,
their parents, and so on — contains the rule's text. With Violin, Viola
and Cello set up as sub-tags of Strings, `Strings { outline: 2px solid
gold }` then styles all three. Off by default.

Changes apply the next time a scene page loads.

## Editing a marker by clicking it

Clicking a marker's colored range on the seek bar, or one of its icons,
jumps to that marker and opens Stash's own edit form for it. That form
lives in the scene's **Markers** tab, so the plugin switches to that tab,
finds the marker's row by its start time (and title), and presses its
Edit button for you.

On by default. To only jump to the marker, switch off Settings → Plugins
→ Marker Improvements → **Click on a marker opens the edit marker
dialog**. (Stash settings can't have a default, so the plugin saves this
one as "on" the first time it runs — that's why the switch starts out on.)

Stash doesn't label those rows or buttons in a way a plugin can target
directly, so this goes by what's shown on screen. If a Stash update
changes the Markers tab's layout, clicking still switches to that tab,
and the browser console says it couldn't find the marker's row.

## Tag bubble on hover

In the scene's Markers tab, hovering a tag shows the bubble it gives a
marker, right next to it — with the same look and custom styles as on
the seek bar:

- options in the tag dropdown while you create or edit a marker,
- tags you've already picked in that form,
- tag badges in the Markers tab's list of markers.

The tag's description, if it has one, shows underneath the image
(cut off after eight lines). A tag with a description but no image shows
just the description; one with neither shows nothing. Stash only shows tag *names* in
those places, so the plugin looks each one up once to find its image. If
a Stash update changes how the form or list is built, the bubble just
doesn't appear there; nothing else is affected.

## Parent tags in the tag dropdown

While you create or edit a marker, each tag in the form's tag dropdown
shows its parent tags after its name, greyed out — `Violin (Strings)`,
or `Solo (Piano, Violin)` for a tag with several parents. That tells
apart tags with similar names and shows where a tag sits in your
hierarchy before you pick it. Tags without a parent look as before.

## Marker list in the Markers tab

The scene's **Markers** tab shows its own marker list in place of
Stash's:

- **One row per marker**: its screenshot on the left — playing the
  marker's preview while you hover it, if Stash has generated one (Tasks →
  Generate → Marker previews) — and on the right
  its title, start – end and length, primary tag, other tags, and the tag
  images its bubble shows (with your custom styles). A marker without an
  end time runs until the next marker, the last one to the end of the
  scene. Markers with the same primary tag share a color stripe.
- **Click a row** to jump to that marker.
- **Editing opens in place**: a row's **Edit** (or clicking a marker on the
  seek bar) opens Stash's edit form right below that marker's row, like an
  accordion, and the sidebar scrolls there — the marker's row at the top,
  the form below it. Save, Cancel or **Close** folds it away again.
- **The marker playing right now is highlighted** in amber: a frame and a
  **▶ Playing** badge on its row, and an outline on its bubble on the
  seek bar (also while the Markers tab isn't open). **The list follows
  playback**: when a new marker starts, its row scrolls to the middle of
  the sidebar. It holds still while you edit, while the list is
  collapsed, for a few seconds after you scroll yourself, and on phones
  (where it would scroll the video out of view).
- **Hide / Show** collapses the list; your browser remembers the choice.

Stash's own marker list is hidden — only the list itself: its **Create
Marker** button (above the plugin's list) and its edit form stay. Clicking
**Create Marker** scrolls the sidebar to the new form, as editing does. Turn on Settings → Plugins →
Marker Improvements → **Also show Stash's own marker list** to see both.

Marker end times need Stash v0.27 or newer; on older versions every
marker runs until the next one.

The edit form is Stash's own, moved into place: the plugin leaves a
placeholder where Stash put it and moves it back the moment you save,
cancel or delete, before Stash handles that click.

## Which tags the marker form offers

Two settings (Settings → Plugins → Marker Improvements) limit the tags the
marker form's **Primary Tag** and **Tags** fields offer — handy when only
part of your tag tree is meant for markers:

- **Marker tags: only under** — only tags below these tags, at any depth.
  E.g. `Instruments, Works`.
- **Marker tags: not under** — leaves out these tags and everything below
  them. E.g. `Genres, Technical`.

Use either or both; tag names separated by commas. Tags already on a
marker stay as they are; this only limits what's offered when you pick.
Tag fields elsewhere in Stash — a scene's Edit tab and so on — aren't
affected. Stash itself does the filtering (the plugin adds a filter to the
tag search the marker form sends), so the list stays complete and sorted;
if anything goes wrong, all tags are offered as usual.

## Marker scrapers

Stash scrapes scenes, galleries and performers, but not markers. This
plugin adds marker scrapers that work the same way: a **Scrape markers…**
button next to **Create Marker** in the Markers tab lists

- every scraper that scrapes the scene itself,
- one entry per scene URL a URL scraper handles, and **other URL…** to
  enter one.

The markers found open in a dialog: tick the ones to create, change
titles, primary tag and tags, and **shift all times** (when the online
video has a longer or shorter intro than your file). Markers already in
the scene at that time are flagged and not ticked. **Create markers**
adds them, and the page updates.

Built in:

- **Video file chapters** — chapters stored in the file (MKV, MP4 …), read
  with Stash's ffprobe.
- **Online chapters (yt-dlp)** — the chapters of the video online (YouTube
  chapters, e.g. a concert's movements), from the scene's URLs or one you
  enter. Needs yt-dlp on the server (the **Path to yt-dlp** setting, else
  Scene Improvements' one, else the PATH).

**Primary tag**: every marker needs one. A scraper can name it per marker;
otherwise the **Primary tag for scraped markers** setting is used (empty:
`Chapter`), and you can change it in the dialog. A primary tag that
doesn't exist yet is created. Other tags are matched by name or alias;
ones that don't exist are left out (and listed).

### Your own marker scrapers

Put them in a folder on the server and enter it as **Marker scrapers
folder**. A scraper is a `.yaml` file in Stash's scraper format, with
`markerByFragment` (scrape the scene) and/or `markerByURL` (scrape a URL):

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
```

The script runs in the scraper's folder. It gets JSON on stdin —
`{"scene": {id, title, code, details, date, urls, files: [{path,
duration}], scene_markers: [...]}}`, plus `"url"` when scraping a URL — and
prints a JSON list of markers:

```json
[{"seconds": 0, "end_seconds": 512.4, "title": "I. Allegro con brio",
  "primary_tag": "Movement", "tags": ["Beethoven"]}]
```

Only `seconds` is required. The environment variables `STASH_FFPROBE` and
`STASH_YTDLP` name the ffprobe and yt-dlp to use. Only `action: script`
is supported. Use `.yaml` (not `.yml`) for scrapers inside Stash's plugins
folder — Stash takes every `.yml` there for a plugin.

## Staying up to date

Whenever a marker is created, edited or deleted — from the edit form,
the Markers tab, anywhere in Stash — the plugin reloads the scene's
markers and its own settings and redraws every bubble, so a new tag
image, a changed time or a removed marker shows up without reloading the
page. It notices this by watching Stash's own save requests, with a
backup check on the seek bar's marker ranges themselves (one appearing,
disappearing or moving) in case a Stash version saves some other way.
Only a change to a marker's time or count is caught by that backup, not
a change to its tags.

It also puts the bubbles back whenever the seek bar and the bubbles no
longer match — when Stash redraws its marker ranges after an edit, or
when the ranges only appear late. The latter is common on phones: mobile
browsers usually don't load the video until you tap play, and Stash only
draws the ranges once it knows the video's length, so the bubbles appear
then.

## Where the symbols show up

Directly inside Stash's own colored marker indicator for that marker —
the small tinted bar (class `.vjs-marker-range`) Stash itself draws on
the seek bar at each marker's timestamp. The bubble is an actual child of
that element (not a separate overlay layered on top) and sits above it,
starting where the marker starts, with a small tail pointing down at that
spot.

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
the icon manually injected into it, Stash re-rendering its marker ranges
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

- The bubbles and the marker list only read markers and tags; markers are
  only created by the marker scrapers, when you click **Create markers**.
- If a scene has a lot of markers close together, their icons can overlap
  a bit on the seek bar; that's a display-only trade-off, nothing is lost
  or hidden from the underlying data.
- Icon size is controlled by `ICON_SIZE_PX` near the top of the script if
  you want them bigger or smaller.
