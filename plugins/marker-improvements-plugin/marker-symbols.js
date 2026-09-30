// Marker Improvements — UI addon
//
// For each scene marker, shows a small "bubble" — one image per tag on it
// that has a real custom image uploaded (Settings on a tag page lets you
// upload one) — floating centered above Stash's own colored marker
// indicator on the video scrubber (class `.vjs-marker-range`, one per
// marker), with a little tail pointing back down at it. It's a real,
// permanent child of that indicator, so it
// shows and hides right along with it — whatever Stash itself does to
// reveal that indicator (e.g. hovering the scrubber) is what reveals the
// bubble too, no separate interaction of its own needed. Click an icon to
// jump straight to that marker.
//
// Since a .vjs-marker-range is React-managed and knows nothing about the
// icon manually injected into it, a seek (which clicking an icon causes)
// can trigger Stash to re-render its marker overlay and wipe that icon
// out as a side effect. ensureSeekRecovery() watches for that per <video>
// element and re-mounts whenever an icon has actually gone missing.
//
// How markers are matched to their indicator:
//   Stash draws one `.vjs-marker-range` element per scene marker on the
//   scrubber, but doesn't expose which is which by id or attribute — so
//   this pairs them up by left-to-right order: every `.vjs-marker-range`
//   found, sorted by its own position along the bar, against every marker
//   from GraphQL, sorted by timestamp. Both lists should always be in the
//   same order and (once the player's finished setting up) the same
//   length, so index i of one is index i of the other.
//   If the counts don't match (the player hasn't drawn its ranges yet, or
//   a future Stash version changes how these are exposed), a console
//   warning says so and only the matching prefix gets icons — nothing
//   crashes, some markers just don't get one that pass. placeSymbols()
//   also waits and retries if no `.vjs-marker-range` elements exist yet
//   at all, since the player can still be initializing when this first
//   runs.
//
// Diagnostics:
//   mountIconsOnMarkerRanges() logs a console.table of the pairing
//   itself — each marker, its matched .vjs-marker-range's measured
//   position/class/pointer-events, and whether an icon was built for it
//   — check that against what actually renders when something looks off.
//
// A tag with no custom image still returns a non-empty `image_path` from
// Stash — it just points at Stash's own generic placeholder, marked with
// a `default=true` query param (the same convention Stash uses for
// performers/studios). hasCustomImage() filters those out, so a tag with
// no real image just doesn't get an icon rather than showing a generic
// placeholder for every tag.

(function () {
  "use strict";

  // Height of a tag icon in the bubbles (scrubber and hover), and in the
  // Markers tab's timeline list. Wide icons get up to twice this in width.
  const ICON_SIZE_PX = 88;
  const LIST_ICON_SIZE_PX = 56;
  // Corner rounding of the bubble and of each image in it. 0 = square.
  const BUBBLE_RADIUS_PX = 0;
  const ICON_RADIUS_PX = 0;
  const MARKER_RANGE_SELECTOR = ".vjs-marker-range";
  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "markerImprovements";

  const MAX_PLACEMENT_RETRIES = 20;
  const PLACEMENT_RETRY_MS = 500;
  // How many of those retries to spend waiting for the number of ranges
  // to match the number of markers before pairing up what's there anyway.
  const MISMATCH_RETRIES = 6;

  // -- GraphQL -------------------------------------------------------

  function callGQL(query, variables) {
    return fetch("/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    })
      .then((r) => r.json())
      .then((json) => {
        if (json.errors) {
          throw new Error(json.errors.map((e) => e.message).join("; "));
        }
        return json.data;
      });
  }

  // Also asks for each marker's end time (Stash v0.27+) and screenshot,
  // for the timeline view. Older versions don't have end_seconds and
  // reject the whole query, so that's retried without it.
  async function fetchMarkers(sceneId) {
    const query = (extra) => `
      query($id: ID!) {
        findScene(id: $id) {
          scene_markers {
            id
            seconds
            ${extra}
            title
            screenshot
            primary_tag { id name image_path }
            tags { id name image_path }
          }
        }
      }`;
    let data;
    try {
      data = await callGQL(query("end_seconds"), { id: sceneId });
    } catch (err) {
      data = await callGQL(query(""), { id: sceneId });
    }
    return data.findScene.scene_markers || [];
  }

  // This plugin's settings (Settings > Plugins), as saved. Read fresh on
  // every scene load, so a change shows up on the next one.
  async function fetchPluginSettings() {
    let settings;
    try {
      const data = await callGQL(`query { configuration { plugins } }`);
      settings = (data.configuration.plugins || {})[PLUGIN_ID] || {};
    } catch (err) {
      console.warn("[Marker Symbols] Couldn't read plugin settings:", err);
      return { editMarkerOnClick: true };
    }
    return applySettingDefaults(settings);
  }

  // Stash plugin settings can't declare a default: one never touched is
  // just missing, and its switch shows "off". "Click opens the marker
  // editor" should start out on, so the first time it's missing this saves
  // it as on — the switch then shows what actually happens. Also carries
  // over the older, inverted "disableEditOnClick" switch if it was set.
  async function applySettingDefaults(settings) {
    if (typeof settings.editMarkerOnClick === "boolean") return settings;
    const updated = { ...settings, editMarkerOnClick: settings.disableEditOnClick !== true };
    delete updated.disableEditOnClick;
    try {
      await callGQL(
        `mutation($plugin_id: ID!, $input: Map!) { configurePlugin(plugin_id: $plugin_id, input: $input) }`,
        { plugin_id: PLUGIN_ID, input: updated }
      );
    } catch (err) {
      console.warn("[Marker Symbols] Couldn't save the default for the marker editor setting:", err);
    }
    return updated;
  }

  // Parses the setting — CSS rules with tag names in place of selectors,
  // e.g. `Violin { outline: 2px solid gold } Piano, Cello { opacity: .6 }`
  // — into a Map of lowercased name text → CSS declarations, in the order
  // written. `*` is kept as its own key and applies to every icon. Text
  // listed in more than one rule gets all of them, in order.
  function parseTagStyles(text) {
    const styles = new Map();
    const rule = /([^{}]+)\{([^{}]*)\}/g;
    let match;
    while ((match = rule.exec(text || "")) !== null) {
      const css = match[2].trim();
      if (!css) continue;
      match[1].split(",").forEach((name) => {
        const key = name.trim().toLowerCase();
        if (!key) return;
        styles.set(key, styles.has(key) ? `${styles.get(key)};${css}` : css);
      });
    }
    return styles;
  }

  // -- helpers ---------------------------------------------------------

  function currentSceneId() {
    const match = window.location.pathname.match(/\/scenes\/(\d+)/);
    return match ? match[1] : null;
  }

  function formatTime(seconds) {
    const s = Math.floor(seconds % 60).toString().padStart(2, "0");
    const m = Math.floor(seconds / 60);
    return `${m}:${s}`;
  }

  // The scene player's video — not just the first <video> on the page,
  // which can be a preview (e.g. in the Markers tab) on some layouts.
  function findVideoEl() {
    return document.querySelector(".video-js video, video.vjs-tech") || document.querySelector("video");
  }

  // -- state / cleanup --------------------------------------------------

  // Every icon-group element we've appended into a .vjs-marker-range, so
  // clearOverlay() can remove just those without touching Stash's own
  // marker-range elements themselves.
  let mountedIcons = [];
  // The marker ranges on screen when bubbles were last mounted (see
  // rangeSignature), and a counter of mounts — so the page watcher near the
  // end can tell when the scrubber no longer matches the bubbles.
  let lastMountSignature = null;
  let mountGeneration = 0;
  let placementTimer = null;
  // {el, prop, original} for every inline overflow style unclipAncestors()
  // overrode, so clearOverlay() can put each one back exactly as found.
  let overflowOverrides = [];
  // Last markers fetched for the current scene, kept around so the seek
  // recovery below (see ensureSeekRecovery) can re-mount without another
  // GraphQL round trip.
  let lastMarkers = null;
  // Parsed "Custom styles per tag" setting for the current scene load
  // (see parseTagStyles), kept alongside lastMarkers for the same reason.
  let tagStyles = new Map();
  // The "Custom styles per bubble" setting, parsed the same way; its CSS
  // goes on a whole bubble (see applyBubbleStyles).
  let bubbleStyles = new Map();
  // Whether clicking a marker's range or icon opens Stash's marker editor
  // (the "Click on a marker opens the edit marker dialog" setting).
  let editOnClick = true;
  // The "Also show Stash's own marker list" setting.
  let showStashMarkerList = false;
  // With the "Custom styles also match parent tags" setting on: tag id →
  // lowercased names of every tag above it in the hierarchy (parents,
  // their parents, …). Empty with the setting off.
  let tagAncestorNames = new Map();
  // Every marker paired with its .vjs-marker-range on the current mount —
  // including markers without an icon — for the range click handler.
  let tickPairs = [];

  function clearOverlay() {
    // (Only ever called after this script has finished loading, so the
    // observer, defined further down, exists by then.)
    if (bubbleResizeObserver) bubbleResizeObserver.disconnect();
    mountedIcons.forEach((el) => el.remove());
    mountedIcons = [];
    tickPairs = [];
    // `original` is whatever that inline style property held before we
    // touched it — including "" if it wasn't set at all, which correctly
    // clears our override back to "nothing" rather than "visible".
    overflowOverrides.forEach(({ el, prop, original }) => {
      el.style[prop] = original;
    });
    overflowOverrides = [];
    if (placementTimer) {
      clearTimeout(placementTimer);
      placementTimer = null;
    }
  }

  // A tag with no custom image uploaded still returns a non-empty
  // `image_path` from Stash — it just points at Stash's own generic
  // placeholder icon, marked with a `default=true` query param (the same
  // convention Stash uses for performers/studios). Without checking for
  // that, every tag would look like it "has an image".
  function hasCustomImage(tag) {
    if (!tag || !tag.image_path) return false;
    try {
      return new URL(tag.image_path, window.location.origin).searchParams.get("default") !== "true";
    } catch (e) {
      // Not a parseable URL for some reason — fall back to a plain
      // substring check rather than assuming it's a real image.
      return !/[?&]default=true\b/.test(tag.image_path);
    }
  }

  // A marker's primary tag plus its other tags, deduped.
  function dedupedTags(marker) {
    const seen = new Set();
    const result = [];
    const consider = (tag) => {
      if (!tag) return;
      const key = tag.id != null ? `id:${tag.id}` : `name:${tag.name}`;
      if (seen.has(key)) return;
      seen.add(key);
      result.push(tag);
    };
    consider(marker.primary_tag);
    (marker.tags || []).forEach(consider);
    return result;
  }

  function tagsWithImages(marker) {
    const seenPaths = new Set();
    return dedupedTags(marker).filter((tag) => {
      if (!hasCustomImage(tag) || seenPaths.has(tag.image_path)) return false;
      seenPaths.add(tag.image_path);
      return true;
    });
  }

  // Two different tags can have the very same picture uploaded, but Stash
  // serves each from its own URL (/tag/<id>/image), so the path check in
  // tagsWithImages() can't catch that. This fingerprints the actual image
  // bytes instead. FNV-1a rather than crypto.subtle, since the latter only
  // exists in secure contexts and Stash is often reached over plain http.
  // Cached per URL so seek recovery re-mounts don't refetch anything.
  const imageFingerprints = new Map();

  function imageFingerprint(url) {
    if (!imageFingerprints.has(url)) {
      const promise = fetch(url, { credentials: "include" })
        .then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`);
          return r.arrayBuffer();
        })
        .then((buf) => {
          const bytes = new Uint8Array(buf);
          let hash = 0x811c9dc5;
          for (let i = 0; i < bytes.length; i++) {
            hash ^= bytes[i];
            hash = Math.imul(hash, 0x01000193);
          }
          return `${bytes.length}:${(hash >>> 0).toString(16)}`;
        })
        .catch(() => null);
      imageFingerprints.set(url, promise);
    }
    return imageFingerprints.get(url);
  }

  // Drops every image in `bubble` whose bytes match one earlier in it, so
  // the same picture only shows once per marker. The kept image's tooltip
  // gets the dropped tag's name added, so no tag silently disappears.
  async function removeDuplicateImages(bubble) {
    const imgs = Array.from(bubble.querySelectorAll("img"));
    const fingerprints = await Promise.all(imgs.map((img) => imageFingerprint(img.src)));
    const keptByFingerprint = new Map();
    imgs.forEach((img, i) => {
      const fp = fingerprints[i];
      if (!fp) return; // couldn't fetch — keep it rather than guess
      const kept = keptByFingerprint.get(fp);
      if (!kept) {
        keptByFingerprint.set(fp, img);
        return;
      }
      if (img.alt) {
        kept.title = kept.title.replace(/\)$/, `, ${img.alt})`);
      }
      img.remove();
    });
  }

  // Builds a small "bubble" for one marker: one image per tag on it that
  // has an image uploaded (primary tag included), floating centered above
  // its .vjs-marker-range container with a little tail pointing back down
  // at it — like a tooltip callout rather than plain icons sitting flush
  // on the bar. Returns null if none of its tags have an image — that
  // marker just gets no bubble, rather than a generic placeholder.
  //
  // `preview` builds the same bubble to show on its own, e.g. when
  // hovering a tag (see showTagBubble): no tail and nothing to click.
  function makeMarkerIcons(marker, video, { preview = false } = {}) {
    const tags = tagsWithImages(marker);
    if (tags.length === 0) return null;

    const primaryName = (marker.primary_tag && marker.primary_tag.name) || "";
    const baseLabel = `${formatTime(marker.seconds)} — ${marker.title || primaryName || "marker"}`;

    const bubble = document.createElement("div");
    bubble.className = "marker-symbols-bubble";
    const placement = preview
      ? ["position:relative", "display:inline-flex"]
      : [
        "position:absolute",
        "left:50%",
        "bottom:100%",
        "transform:translateX(-50%)",
        "margin-bottom:6px",
        "display:flex",
      ];
    bubble.style.cssText = [
      ...placement,
      "flex-direction:column",
      "align-items:center",
      "gap:2px",
      "padding:3px 4px",
      // Light background: mix-blend-mode:multiply on the images (below)
      // only reads correctly against a light backdrop — a white/light
      // area behind an image blends away cleanly, while a dark one just
      // crushes the whole image toward black.
      "background:rgba(255,255,255,0.92)",
      `border-radius:${BUBBLE_RADIUS_PX}px`,
      "box-shadow:0 2px 6px rgba(0,0,0,0.55)",
      // Always visible/interactive — this is a real child of the marker's
      // own .vjs-marker-range now, so it shows and hides right along with
      // that indicator (however Stash itself decides to show it) rather
      // than needing a separate hover trigger of its own. pointer-events
      // is set explicitly since it's an inherited CSS property — a
      // .vjs-marker-range styled pointer-events:none (common, so it
      // doesn't interfere with dragging the real seek handle) would
      // otherwise make this unclickable too.
      "pointer-events:auto",
    ].join(";");

    // The tail: a small square rotated 45° so one corner points straight
    // down at the marker, half-overlapping the bubble's own bottom edge.
    const tail = document.createElement("div");
    tail.style.cssText = [
      "position:absolute",
      "left:50%",
      "top:100%",
      "width:8px",
      "height:8px",
      "margin:-4px 0 0 -4px",
      // Same background as the bubble, including one set by a custom
      // bubble style, so the tail always matches.
      "background:inherit",
      "transform:rotate(45deg)",
      "pointer-events:none",
    ].join(";");
    if (!preview) bubble.appendChild(tail);

    const jumpToMarker = (e) => {
      e.stopPropagation();
      e.preventDefault();
      video.currentTime = marker.seconds;
      if (editOnClick) openMarkerEditor(marker);
    };

    tags.forEach((tag) => {
      const label = preview ? tag.name || "" : tag.name ? `${baseLabel} (${tag.name})` : baseLabel;
      const img = document.createElement("img");
      img.src = tag.image_path;
      img.alt = tag.name || "marker";
      img.dataset.tagName = tag.name || "";
      img.dataset.tagId = tag.id || "";
      img.title = label;
      img.style.cssText = [
        preview ? "cursor:default" : "cursor:pointer", "user-select:none", "flex:none",
        // Fixed height, width following the image's own shape (capped so
        // a very wide banner doesn't stretch the bubble across the bar),
        // and `contain` so nothing is ever cropped — a square box with
        // `cover` cut the sides/top off any image that wasn't square.
        `height:${ICON_SIZE_PX}px`,
        "width:auto",
        `max-width:${ICON_SIZE_PX * 2}px`,
        "object-fit:contain",
        `border-radius:${ICON_RADIUS_PX}px`,
        "border:1px solid rgba(0,0,0,0.2)",
        // Always a white background behind the image — transparent areas
        // of a tag image show white, whatever is behind the bubble.
        "background:#fff",
        "mix-blend-mode:multiply",
      ].join(";");
      if (!preview) img.addEventListener("click", jumpToMarker);
      // If this particular tag's image fails to load, just drop it — the
      // marker's other tag images (if any) are unaffected.
      img.addEventListener("error", () => img.remove());
      bubble.appendChild(img);
    });

    if (tags.length > 1) removeDuplicateImages(bubble);
    applyTagStyles(bubble);
    applyBubbleStyles(bubble, dedupedTags(marker));

    return bubble;
  }

  // Applies the "Custom styles per tag" setting to a bubble's icons. They
  // go on last, so they can override the icon's built-in styles above.
  // A rule matches every tag whose name contains its text, so `Violin`
  // also styles "Violin I" and "Solo Violin". `*` goes first; the rest
  // follow in the order they're written, so a later rule wins where two
  // match the same icon and set the same property.
  //
  // With "Custom styles also match parent tags" on, the names of every tag
  // above this one count too (see tagAncestorNames), so a rule for
  // `Strings` also styles a Violin tag that sits under a Strings tag.
  function applyTagStyles(bubble) {
    bubble.querySelectorAll("img").forEach((img) => {
      const names = namesToMatch([{ id: img.dataset.tagId, name: img.dataset.tagName }]);
      matchingCss(tagStyles, names).forEach((css) => {
        img.style.cssText += `;${css}`;
      });
    });
  }

  // Applies the "Custom styles per bubble" setting to a whole bubble. A
  // rule matches when any of the marker's tags matches it — all of them,
  // including tags without an image — with the same name-contains and
  // parent-tag rules as the icon styles.
  function applyBubbleStyles(bubble, tags) {
    matchingCss(bubbleStyles, namesToMatch(tags)).forEach((css) => {
      bubble.style.cssText += `;${css}`;
    });
  }

  // The lowercased names a style rule is matched against for `tags`: their
  // own names, plus — with "also match parent tags" on — the names of
  // every tag above them.
  function namesToMatch(tags) {
    const names = [];
    tags.forEach((tag) => {
      if (!tag) return;
      names.push((tag.name || "").toLowerCase());
      names.push(...(tagAncestorNames.get(tag.id) || []));
    });
    return names;
  }

  // The CSS of every rule in `rules` that matches one of `names`: `*`
  // first, then the rest in the order written.
  function matchingCss(rules, names) {
    const css = [];
    if (rules.has("*")) css.push(rules.get("*"));
    rules.forEach((ruleCss, key) => {
      if (key !== "*" && names.some((name) => ruleMatches(key, name))) css.push(ruleCss);
    });
    return css;
  }

  // Whether a rule's name matches a (lowercased) tag name. Without a `*`
  // the name only has to appear somewhere in the tag name ("violin"
  // matches "solo violin"). With a `*` it's a pattern for the whole tag
  // name, `*` standing for any text: "solo*" = starts with "solo",
  // "*concerto" = ends with "concerto", "concerto*piano" = both.
  const rulePatterns = new Map(); // rule name → RegExp, built once each
  function ruleMatches(key, name) {
    if (!key.includes("*")) return name.includes(key);
    if (!rulePatterns.has(key)) {
      const escaped = key.split("*").map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&"));
      rulePatterns.set(key, new RegExp(`^${escaped.join(".*")}$`));
    }
    return rulePatterns.get(key).test(name);
  }

  // Every tag's ancestors' names (lowercased), from one request for the
  // whole tag hierarchy. A tag that is (through some chain) its own
  // ancestor is only visited once, so a loop can't hang this.
  async function fetchTagAncestorNames() {
    const data = await callGQL(`query { findTags(filter: { per_page: -1 }) { tags { id name parents { id } } } }`);
    const byId = new Map(data.findTags.tags.map((t) => [t.id, t]));
    const result = new Map();
    byId.forEach((tag, id) => {
      const names = [];
      const seen = new Set([id]);
      const stack = (tag.parents || []).map((p) => p.id);
      while (stack.length) {
        const parent = byId.get(stack.pop());
        if (!parent || seen.has(parent.id)) continue;
        seen.add(parent.id);
        names.push(parent.name.toLowerCase());
        (parent.parents || []).forEach((p) => stack.push(p.id));
      }
      if (names.length) result.set(id, names);
    });
    return result;
  }

  // A .vjs-marker-range element — and sometimes an ancestor of it too —
  // can clip its content (overflow:hidden), usually just to keep the
  // rounded-corner track/fill looking tidy. A 22px icon appended *inside*
  // it would get silently cut down to an invisible sliver by that. This
  // walks up from `el` to `stop` (inclusive) and forces
  // `overflow: visible` on anything found clipping, so the icon can be a
  // true DOM child and still show up poking slightly above/below the
  // range's own thin box. Original values are recorded in
  // `overflowOverrides` for clearOverlay() to restore.
  function unclipAncestors(el, stop) {
    let node = el;
    let guard = 0;
    while (node && node.nodeType === 1 && guard < 8) {
      const computed = getComputedStyle(node);
      ["overflow", "overflowX", "overflowY"].forEach((prop) => {
        if (computed[prop] === "hidden" || computed[prop] === "clip") {
          overflowOverrides.push({ el: node, prop, original: node.style[prop] });
          node.style[prop] = "visible";
        }
      });
      if (node === stop) break;
      node = node.parentElement;
      guard++;
    }
  }

  // Where every marker range on the page sits, as one string: changes when
  // a range is added, removed or moved, not when anything else changes.
  // Rounded to 0.1% of the bar: finer than that, a position read from the
  // layout (when Stash doesn't set it as a percentage) can shift slightly
  // just because something else on the page resized — e.g. a dropdown
  // opening — which would look like the markers moved.
  function rangeSignature() {
    return findMarkerRangeElements(document).map((t) => tickLeftPct(t).toFixed(1)).sort().join(",");
  }

  function findMarkerRangeElements(root) {
    return Array.from((root || document).querySelectorAll(MARKER_RANGE_SELECTOR));
  }

  // Where a marker-range element sits along the bar, as a % — read from
  // its own inline `left` style first (how Stash actually positions these
  // — works even before/without layout), falling back to measuring
  // against its offsetParent if that's not set for some reason.
  function tickLeftPct(tick) {
    const inlineLeft = tick.style.left;
    if (inlineLeft && inlineLeft.endsWith("%")) {
      const v = parseFloat(inlineLeft);
      if (!Number.isNaN(v)) return v;
    }
    const parent = tick.offsetParent;
    if (parent) {
      const parentRect = parent.getBoundingClientRect();
      if (parentRect.width) {
        return ((tick.getBoundingClientRect().left - parentRect.left) / parentRect.width) * 100;
      }
    }
    return 0;
  }

  // Mounts `iconGroupEl` as an actual child of `tick` — one of Stash's own
  // .vjs-marker-range elements.
  function mountIconOnTick(tick, iconGroupEl, unclipRoot) {
    const computed = getComputedStyle(tick);
    if (computed.position === "static") {
      overflowOverrides.push({ el: tick, prop: "position", original: tick.style.position });
      tick.style.position = "relative";
    }
    // Decorative marker indicators like this are commonly styled
    // pointer-events:none by the player so they don't interfere with
    // dragging the real seek handle underneath — but that's harmless
    // here, since the icon group explicitly sets its own
    // pointer-events:auto (see makeMarkerIcons), which — being an
    // inherited CSS property — takes over for its own subtree regardless
    // of what the tick itself is set to. No need to touch the tick's own
    // pointer-events at all.
    unclipAncestors(tick, unclipRoot);

    tick.appendChild(iconGroupEl);
  }

  // .vjs-marker-range is a React-managed element that knows nothing about
  // the icon we manually injected into it. Clicking an icon seeks the
  // video (see jumpToMarker in makeMarkerIcons), and Stash re-rendering
  // its marker overlay in response to that (e.g. to update which marker
  // is "active") can wipe our injected children out from under us as a
  // side effect, even though nothing we did asked for that. This binds a
  // one-time "seeked" listener per <video> element that re-mounts
  // whenever any of our icons has actually gone missing from the DOM.
  function ensureSeekRecovery(video) {
    if (video.__markerSymbolsSeekBound) return;
    video.__markerSymbolsSeekBound = true;
    video.addEventListener("seeked", () => {
      if (!lastMarkers || !lastMarkers.length) return;
      if (mountedIcons.length && mountedIcons.some((el) => !el.isConnected)) {
        clearOverlay();
        mountIconsOnMarkerRanges(video, lastMarkers);
      }
    });
  }

  // Parses a Stash timestamp ("1:23", "01:23" or "1:02:03") to seconds.
  function timestampToSeconds(text) {
    return text.split(":").reduce((total, part) => total * 60 + Number(part), 0);
  }

  // Opens Stash's own edit form for `marker`. That form only exists in the
  // scene page's Markers tab, where every marker is listed with an Edit
  // button — so this switches to that tab, finds the marker's row by its
  // start time (and title, when it has one), and clicks the row's button.
  // Stash doesn't mark rows or buttons with ids, so this goes by what's
  // visible: if a Stash update changes that layout, it still switches to
  // the Markers tab and warns in the console instead of doing nothing.
  function openMarkerEditor(marker) {
    // Opens as an accordion under the marker's row in the timeline view, if
    // it's there (and puts back any form that's open elsewhere first).
    requestAccordion(marker);
    const tab =
      document.querySelector('[data-rb-event-key="scene-markers-panel"]') ||
      Array.from(document.querySelectorAll(".nav-tabs .nav-link"))
        .find((el) => /marker/i.test(el.textContent));
    if (!tab) {
      console.warn("[Marker Symbols] Couldn't find the scene's Markers tab to open the editor");
      return;
    }
    if (!tab.classList.contains("active")) tab.click();

    // The tab's content renders a moment after the click, so look a few
    // times before giving up.
    let attempts = 0;
    const tryOpen = () => {
      const panel =
        document.getElementById("scene-markers-panel") ||
        document.querySelector(".tab-pane.active");
      const row = panel && findMarkerRow(panel, marker);
      if (row) {
        const buttons = Array.from(row.querySelectorAll("button"));
        const edit =
          buttons.find((b) => /^(edit|bearbeiten)$/i.test(b.textContent.trim())) ||
          buttons[buttons.length - 1];
        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
        if (edit) edit.click();
        return;
      }
      if (++attempts < 10) {
        setTimeout(tryOpen, 100);
      } else {
        console.warn(`[Marker Symbols] Opened the Markers tab but couldn't find the row for the ${formatTime(marker.seconds)} marker`);
      }
    };
    tryOpen();
  }

  // The smallest element in the Markers tab that holds one marker's
  // buttons and its time — found by walking up from each button until an
  // ancestor shows a timestamp, then comparing that timestamp (±1s, for
  // rounding) and the title with `marker`'s.
  function findMarkerRow(panel, marker) {
    const timestamp = /\d+(?::\d{1,2}){1,2}/;
    const wanted = Math.floor(marker.seconds);
    const title = (marker.title || "").trim().toLowerCase();
    for (const button of panel.querySelectorAll("button")) {
      // Skip this plugin's own timeline view, which sits in the same tab
      // and shows the same times and titles — its Edit button calls this.
      if (button.closest(`#${TIMELINE_ID}`)) continue;
      let row = button.parentElement;
      while (row && row !== panel && !timestamp.test(row.textContent)) row = row.parentElement;
      if (!row || row === panel) continue;
      const start = timestampToSeconds(row.textContent.match(timestamp)[0]);
      if (Math.abs(start - wanted) > 1) continue;
      if (title && !row.textContent.toLowerCase().includes(title)) continue;
      return row;
    }
    return null;
  }

  // Clicking a marker's own colored range on the scrubber opens its
  // editor too. The range is often pointer-events:none (so it doesn't get
  // in the way of dragging the seek handle), which means it never gets a
  // click itself — so this listens on the whole player instead and checks
  // whether the click landed inside a range's box. Clicks on our own
  // bubbles are left to their own handler. The player's usual seek still
  // happens, since nothing here stops the event.
  function ensureRangeClickEditing(root) {
    if (root.__markerSymbolsClickBound) return;
    root.__markerSymbolsClickBound = true;
    root.addEventListener("click", (e) => {
      if (!editOnClick || e.target.closest(".marker-symbols-bubble")) return;
      const pair = tickPairs.find(({ tick }) => {
        const r = tick.getBoundingClientRect();
        // A few px of slack vertically: the range is often only 2-4px tall.
        return e.clientX >= r.left && e.clientX <= r.right &&
          e.clientY >= r.top - 3 && e.clientY <= r.bottom + 3;
      });
      if (pair) openMarkerEditor(pair.marker);
    }, true);
  }

  // -- bubbles only once the video has started ----------------------------------
  //
  // Before the video has played at all, the scrubber shows no bubbles. A
  // class on the player marks that state and a style rule hides the bubbles
  // inside it (the hover bubbles in the Markers tab aren't inside the player,
  // so they're unaffected). It's set again when a new video loads.

  const NOT_STARTED_CLASS = "marker-symbols-not-started";

  function ensureStyleSheet() {
    if (document.getElementById("marker-symbols-style")) return;
    const style = document.createElement("style");
    style.id = "marker-symbols-style";
    style.textContent = `.${NOT_STARTED_CLASS} .marker-symbols-bubble { display: none !important; }`;
    document.head.appendChild(style);
  }

  function ensureStartTracking(video) {
    ensureStyleSheet();
    const root = video.closest(".video-js") || video.parentElement;
    const update = () => {
      // `played` is empty until the video has actually played, and is
      // emptied again when a new video loads.
      const started = video.played && video.played.length > 0;
      root.classList.toggle(NOT_STARTED_CLASS, !started);
      if (started) scheduleBubbleLayout();
    };
    update();
    if (video.__markerSymbolsStartBound) return;
    video.__markerSymbolsStartBound = true;
    ["playing", "emptied", "loadstart"].forEach((type) => video.addEventListener(type, update));
  }

  // -- bubbles don't overlap -------------------------------------------------------
  //
  // Bubbles of markers close together would sit on top of each other. This
  // stacks them in rows instead: left to right, each bubble goes into the
  // lowest row where it doesn't touch the bubble before it, and each row sits
  // above the tallest bubble of the row below. A raised bubble gets a thin
  // line down to its marker, so it's still clear which marker it belongs to.
  //
  // Sizes change as images load, when the player is resized, and when the
  // ranges (and so the bubbles) are shown or hidden, so a ResizeObserver
  // re-runs the layout whenever any bubble changes size.

  const BUBBLE_GAP_PX = 4;
  let layoutPending = false;
  const bubbleResizeObserver =
    typeof ResizeObserver === "function" ? new ResizeObserver(() => scheduleBubbleLayout()) : null;

  function scheduleBubbleLayout() {
    if (layoutPending) return;
    layoutPending = true;
    requestAnimationFrame(() => {
      layoutPending = false;
      layoutBubbles();
    });
  }

  function setBubbleLift(bubble, lift) {
    bubble.style.marginBottom = `${6 + lift}px`;
    let line = bubble.querySelector(".marker-symbols-connector");
    if (!lift) {
      if (line) line.remove();
      return;
    }
    if (!line) {
      line = document.createElement("div");
      line.className = "marker-symbols-connector";
      line.style.cssText =
        "position:absolute;left:50%;top:100%;width:2px;margin-left:-1px;background:inherit;pointer-events:none;";
      bubble.appendChild(line);
    }
    line.style.height = `${lift + 6}px`;
  }

  function layoutBubbles() {
    // Only bubbles on screen right now: a hidden one has no size.
    const items = mountedIcons
      .filter((b) => b.isConnected && b.offsetWidth)
      .map((b) => {
        const tick = b.parentElement.getBoundingClientRect();
        const center = tick.left + tick.width / 2; // bubbles are centered on their marker
        return { b, left: center - b.offsetWidth / 2, right: center + b.offsetWidth / 2, height: b.offsetHeight };
      })
      .sort((x, y) => x.left - y.left);

    const rows = []; // per row: right edge of its last bubble, tallest bubble
    items.forEach((item) => {
      let row = rows.findIndex((r) => r.right + BUBBLE_GAP_PX <= item.left);
      if (row === -1) {
        row = rows.length;
        rows.push({ right: -Infinity, height: 0 });
      }
      rows[row].right = item.right;
      rows[row].height = Math.max(rows[row].height, item.height);
      item.row = row;
    });

    const lifts = [];
    let lift = 0;
    rows.forEach((r, i) => {
      lifts[i] = lift;
      lift += r.height + BUBBLE_GAP_PX;
    });
    items.forEach((item) => setBubbleLift(item.b, lifts[item.row]));
  }

  // Pairs every .vjs-marker-range found (sorted left-to-right) against
  // every marker from Stash (sorted by timestamp), index for index, and
  // mounts each marker's icon(s) into its matched element.
  function mountIconsOnMarkerRanges(video, markers) {
    lastMountSignature = rangeSignature();
    mountGeneration++;
    const root = video.closest(".video-js, .vjs-container") || document;
    const ticks = findMarkerRangeElements(root).sort((a, b) => tickLeftPct(a) - tickLeftPct(b));
    const sortedMarkers = markers.slice().sort((a, b) => a.seconds - b.seconds);

    const pairCount = Math.min(ticks.length, sortedMarkers.length);
    if (ticks.length !== sortedMarkers.length) {
      console.warn(
        `[Marker Symbols] Found ${ticks.length} ${MARKER_RANGE_SELECTOR} element(s) for ` +
        `${sortedMarkers.length} marker(s) from Stash — counts don't match, so only the first ` +
        `${pairCount} (by left-to-right order) got paired up. The rest get no icon this pass.`
      );
    }

    const pairingLog = [];
    let mountedCount = 0;
    tickPairs = [];
    ensureRangeClickEditing(root);
    for (let i = 0; i < pairCount; i++) {
      const marker = sortedMarkers[i];
      const tick = ticks[i];
      tickPairs.push({ tick, marker });
      const computed = getComputedStyle(tick);
      const iconGroup = makeMarkerIcons(marker, video);
      const label = `${formatTime(marker.seconds)} ${marker.title || (marker.primary_tag && marker.primary_tag.name) || marker.id}`;
      pairingLog.push({
        i,
        marker: label,
        "tick left%": tickLeftPct(tick).toFixed(2),
        "tick class": tick.className,
        "tick pointer-events": computed.pointerEvents,
        "icon built": !!iconGroup,
      });
      if (!iconGroup) continue;
      // console.table can't show a live, clickable DOM node — this can:
      // click the element in devtools to jump straight to it in Elements.
      console.log(`[Marker Symbols] #${i} "${label}" → attaching into:`, tick);
      mountIconOnTick(tick, iconGroup, root);
      mountedIcons.push(iconGroup);
      mountedCount++;
    }

    console.info(
      `[Marker Symbols] Paired ${pairCount} marker(s) to ${MARKER_RANGE_SELECTOR} element(s) ` +
      `by left-to-right order; mounted ${mountedCount} icon(s) ("icon built": false means that ` +
      "marker has no tag with a real custom image). Pairing detail:"
    );
    console.table(pairingLog);

    ensureStartTracking(video);
    if (bubbleResizeObserver) mountedIcons.forEach((b) => bubbleResizeObserver.observe(b));
    scheduleBubbleLayout();
  }

  async function placeSymbols(sceneId, attempt) {
    attempt = attempt || 0;
    const video = findVideoEl();
    if (!video) {
      retryPlacement(sceneId, attempt);
      return;
    }

    let markers, settings;
    try {
      [markers, settings] = await Promise.all([fetchMarkers(sceneId), fetchPluginSettings()]);
    } catch (err) {
      console.error("[Marker Symbols] Failed to fetch markers:", err);
      return;
    }
    if (currentSceneId() !== sceneId) return; // navigated away while fetching
    // Settings first: the hover bubble needs the tag styles even on a
    // scene that has no markers yet.
    tagStyles = parseTagStyles(settings.tagStyles || "");
    bubbleStyles = parseTagStyles(settings.bubbleStyles || "");
    editOnClick = settings.editMarkerOnClick !== false;
    showStashMarkerList = settings.showStashMarkerList === true;
    tagAncestorNames = new Map();
    if (settings.styleParentTags && (tagStyles.size || bubbleStyles.size)) {
      try {
        tagAncestorNames = await fetchTagAncestorNames();
      } catch (err) {
        console.warn("[Marker Symbols] Couldn't load the tag hierarchy; styles match own tag names only:", err);
      }
      if (currentSceneId() !== sceneId) return;
    }
    showTimeline(markers);
    if (!markers.length) return;

    const root = video.closest(".video-js, .vjs-container") || document;
    const tickCount = findMarkerRangeElements(root).length;
    if (!tickCount) {
      // Stash hasn't drawn its marker-range elements yet (player still
      // initializing) — wait and try again rather than giving up.
      retryPlacement(sceneId, attempt);
      return;
    }
    if (tickCount !== markers.length && attempt < MISMATCH_RETRIES) {
      // Right after a marker is added or deleted, Stash can still be
      // redrawing its ranges — give it a moment before pairing them up,
      // or every marker after the change would get the wrong icon.
      retryPlacement(sceneId, attempt);
      return;
    }

    lastMarkers = markers;
    ensureSeekRecovery(video);
    clearOverlay();
    mountIconsOnMarkerRanges(video, markers);
  }

  function retryPlacement(sceneId, attempt) {
    if (attempt >= MAX_PLACEMENT_RETRIES) return;
    placementTimer = setTimeout(() => {
      if (currentSceneId() !== sceneId) return;
      placeSymbols(sceneId, attempt + 1);
    }, PLACEMENT_RETRY_MS);
  }

  function refreshForCurrentPage() {
    clearOverlay();
    // The marker list stays while its scene does: renderTimeline only
    // rebuilds it once the fresh markers turn out to differ.
    if (currentSceneId() !== timelineSceneId) {
      timelineMarkers = [];
      removeTimeline();
    }
    const sceneId = currentSceneId();
    if (!sceneId) return;
    placeSymbols(sceneId, 0);
  }

  // -- marker list view in the Markers tab -------------------------------------
  //
  // At the top of the scene's Markers tab: a list with one row per marker —
  // its screenshot on the left, all its details on the right. Clicking a
  // row jumps to that marker; the row's Edit button opens Stash's own edit
  // form (see openMarkerEditor). The marker playing right now is
  // highlighted, following playback. Stash's own marker list below it is
  // hidden (see hideStashMarkerList), unless the "Also show Stash's own
  // marker list" setting is on.

  const TIMELINE_ID = "marker-symbols-timeline";
  const TIMELINE_COLLAPSED_KEY = "markerImprovements.timelineCollapsed";
  const THUMB_WIDTH_PX = 144;

  // Markers of the scene on screen, sorted by start, each with `start`,
  // `end` and `index` worked out for the view.
  let timelineMarkers = [];

  function readCollapsed() {
    try {
      return localStorage.getItem(TIMELINE_COLLAPSED_KEY) === "1";
    } catch (e) {
      return false;
    }
  }

  function writeCollapsed(collapsed) {
    try {
      localStorage.setItem(TIMELINE_COLLAPSED_KEY, collapsed ? "1" : "0");
    } catch (e) {
      // Not remembered this time — nothing else depends on it.
    }
  }

  function formatDuration(seconds) {
    const total = Math.max(0, Math.round(seconds));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
  }

  // A steady color per primary tag, so markers of the same kind match.
  function colorFor(name) {
    let hash = 0;
    for (const ch of name || "") hash = (hash * 31 + ch.charCodeAt(0)) | 0;
    return `hsl(${Math.abs(hash) % 360}, 55%, 50%)`;
  }

  function sceneDuration() {
    const video = findVideoEl();
    return video && Number.isFinite(video.duration) && video.duration > 0 ? video.duration : null;
  }

  // Start/end for every marker: its own end time if it has one, else the
  // next marker's start, else the end of the scene.
  function prepareTimeline(markers) {
    const sorted = markers.slice().sort((a, b) => a.seconds - b.seconds);
    const duration = sceneDuration();
    return sorted.map((m, index) => {
      const next = sorted.find((o) => o.seconds > m.seconds);
      let end = m.end_seconds != null && m.end_seconds > m.seconds ? m.end_seconds : next ? next.seconds : duration;
      if (end == null) end = m.seconds; // duration not known yet; fixed once the video has loaded
      return { ...m, start: m.seconds, end, index };
    });
  }

  // Seeks to a marker's start.
  function seekTo(marker) {
    const video = findVideoEl();
    if (video) video.currentTime = marker.start;
  }

  function buildMarkerRow(m) {
    const name = m.title || (m.primary_tag && m.primary_tag.name) || "Marker";
    const row = document.createElement("div");
    row.dataset.markerIndex = String(m.index);
    row.dataset.markerId = String(m.id);
    row.style.cssText =
      "display:flex;gap:12px;padding:8px;border-radius:4px;cursor:pointer;" +
      `border-left:4px solid ${colorFor(m.primary_tag && m.primary_tag.name)};margin-bottom:6px;` +
      "background:rgba(255,255,255,0.04);";
    row.addEventListener("click", () => seekTo(m));

    // Left: the marker's screenshot.
    const thumb = document.createElement("img");
    thumb.src = m.screenshot || "";
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.style.cssText =
      `width:${THUMB_WIDTH_PX}px;aspect-ratio:16/9;object-fit:cover;flex:none;border-radius:3px;background:#000;`;
    thumb.addEventListener("error", () => {
      thumb.style.visibility = "hidden";
    });
    row.appendChild(thumb);

    // Right: all the details.
    const details = document.createElement("div");
    details.style.cssText = "flex:1;min-width:0;display:flex;flex-direction:column;gap:4px;";

    const head = document.createElement("div");
    head.style.cssText = "display:flex;align-items:baseline;gap:8px;";
    const title = document.createElement("strong");
    title.textContent = name;
    title.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    head.appendChild(title);
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "btn btn-link btn-sm marker-symbols-edit";
    edit.textContent = "Edit";
    edit.style.cssText = "margin-left:auto;padding:0;flex:none;";
    edit.addEventListener("click", (e) => {
      e.stopPropagation();
      // Clicking Edit on the row whose form is open closes it again.
      if (movedForm && movedForm.row === row && closeAccordion()) return;
      seekTo(m);
      openMarkerEditor(m);
    });
    head.appendChild(edit);
    details.appendChild(head);

    const time = document.createElement("div");
    time.style.cssText = "font-size:0.85em;opacity:0.75;";
    time.textContent = `${formatDuration(m.start)} – ${formatDuration(m.end)} · ${formatDuration(m.end - m.start)}`;
    details.appendChild(time);

    if (m.primary_tag) {
      const primary = document.createElement("div");
      primary.style.cssText = "font-size:0.85em;";
      primary.textContent = `Primary tag: ${m.primary_tag.name}`;
      details.appendChild(primary);
    }

    const others = (m.tags || []).filter((t) => !m.primary_tag || t.id !== m.primary_tag.id);
    if (others.length) {
      const tags = document.createElement("div");
      tags.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;";
      others.forEach((t) => {
        const badge = document.createElement("span");
        badge.className = "badge badge-secondary";
        badge.textContent = t.name;
        tags.appendChild(badge);
      });
      details.appendChild(tags);
    }

    // The same icons the marker's bubble shows on the scrubber.
    const images = tagsWithImages(m);
    if (images.length) {
      const icons = document.createElement("div");
      icons.style.cssText = "display:flex;gap:4px;";
      images.forEach((t) => {
        const img = document.createElement("img");
        img.src = t.image_path;
        img.alt = t.name || "";
        img.title = t.name || "";
        img.dataset.tagName = t.name || "";
        img.dataset.tagId = t.id || "";
        img.style.cssText =
          `height:${LIST_ICON_SIZE_PX}px;width:auto;max-width:${LIST_ICON_SIZE_PX * 2}px;` +
          "object-fit:contain;background:#fff;";
        img.addEventListener("error", () => img.remove());
        icons.appendChild(img);
      });
      applyTagStyles(icons);
      details.appendChild(icons);
    }

    row.appendChild(details);
    return row;
  }

  function removeTimeline() {
    // Put Stash's form back first if it's open inside this view — see
    // "edit form as an accordion" below.
    restoreForm();
    const view = document.getElementById(TIMELINE_ID);
    if (view) view.remove();
  }

  // (Re)builds the view at the top of the Markers tab. Does nothing until
  // that tab is on screen; the observer below brings us back when it is.
  // What the list shows, as one string — the list is only rebuilt when this
  // changes. (Rebuilding redraws the whole tab, so the page jumps, and it
  // would close an edit form that's open in the list.)
  function timelineKey(markers) {
    return JSON.stringify([
      Math.round(sceneDuration() || 0),
      markers.map((m) => [
        m.id, m.seconds, m.end_seconds, m.title, m.screenshot,
        m.primary_tag && m.primary_tag.id, (m.tags || []).map((t) => t.id),
      ]),
    ]);
  }

  // Set while a rebuild waits for the open edit form to close.
  let timelineRenderPending = false;

  function renderTimeline() {
    const panel = findMarkersPanel();
    if (!panel || !timelineMarkers.length) {
      removeTimeline();
      return;
    }
    const key = timelineKey(timelineMarkers);
    const existing = document.getElementById(TIMELINE_ID);
    if (existing && existing.parentElement === panel && existing.dataset.key === key) return;
    if (movedForm) {
      // Don't pull the form out from under someone typing: rebuild once
      // it's closed (see restoreForm).
      timelineRenderPending = true;
      return;
    }
    timelineRenderPending = false;
    timelineMarkers = prepareTimeline(timelineMarkers);

    removeTimeline();
    const view = document.createElement("div");
    view.id = TIMELINE_ID;
    view.dataset.key = key;
    view.style.cssText = "margin-bottom:16px;";

    const header = document.createElement("div");
    header.style.cssText = "display:flex;align-items:center;gap:8px;margin-bottom:8px;";
    const heading = document.createElement("strong");
    heading.textContent = `${timelineMarkers.length} marker${timelineMarkers.length === 1 ? "" : "s"}`;
    header.appendChild(heading);
    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "btn btn-secondary btn-sm";
    toggle.style.marginLeft = "auto";
    header.appendChild(toggle);
    view.appendChild(header);

    const body = document.createElement("div");
    timelineMarkers.forEach((m) => body.appendChild(buildMarkerRow(m)));
    view.appendChild(body);

    const applyCollapsed = (collapsed) => {
      body.style.display = collapsed ? "none" : "";
      toggle.textContent = collapsed ? "Show" : "Hide";
    };
    applyCollapsed(readCollapsed());
    toggle.addEventListener("click", () => {
      const collapsed = body.style.display !== "none";
      writeCollapsed(collapsed);
      applyCollapsed(collapsed);
    });

    panel.insertBefore(view, panel.firstChild);
    updateTimelineProgress();
    hideStashMarkerList(panel);
  }

  // Hides Stash's own marker list in the Markers tab, which this view
  // replaces. Only the list: the "Create Marker" button and Stash's edit
  // form stay. Nothing is removed — its rows and their Edit buttons stay in
  // the page, hidden, because openMarkerEditor presses those for us.
  //
  // Stash doesn't label the list, so this goes by content: a part of the
  // tab that shows marker times (like "1:23") is list; the "Create Marker"
  // button bar has none. A part that holds something to keep as well as
  // times — the form, or a regular button like "Create Marker" (the list's
  // own buttons are link-style) — is looked into, so just the list inside
  // it is hidden.
  function hideStashMarkerList(container) {
    if (showStashMarkerList) return;
    for (const child of Array.from(container.children)) {
      if (child.id === TIMELINE_ID || child.dataset.markerSymbolsHidden) continue;
      if (child.tagName === "FORM" || child.matches("button.btn-primary")) continue;
      if (!/\d+:\d{2}/.test(child.textContent)) continue;
      if (child.querySelector("form, button.btn-primary")) {
        hideStashMarkerList(child);
        continue;
      }
      child.style.display = "none";
      child.dataset.markerSymbolsHidden = "1";
    }
  }

  // Highlights the marker playing right now.
  function updateTimelineProgress() {
    const view = document.getElementById(TIMELINE_ID);
    const video = findVideoEl();
    if (!view || !video) return;
    const t = video.currentTime;
    const playing = new Set(timelineMarkers.filter((m) => t >= m.start && t < m.end).map((m) => String(m.index)));
    view.querySelectorAll("[data-marker-index]").forEach((row) => {
      row.style.background = playing.has(row.dataset.markerIndex) ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.04)";
    });
  }

  function ensureTimelineTracking(video) {
    if (video.__markerSymbolsTimelineBound) return;
    video.__markerSymbolsTimelineBound = true;
    video.addEventListener("timeupdate", updateTimelineProgress);
    // The scene's length is only known once the video has loaded, and the
    // last marker's end (and the bar's scale) depend on it.
    video.addEventListener("loadedmetadata", renderTimeline);
  }

  // The scene the marker list belongs to.
  let timelineSceneId = null;

  function showTimeline(markers) {
    timelineMarkers = markers;
    timelineSceneId = currentSceneId();
    const video = findVideoEl();
    if (video) ensureTimelineTracking(video);
    renderTimeline();
  }

  // Stash redraws its own marker list at times (e.g. while you edit), which
  // would show it again. This hides it right away — observer callbacks run
  // before the browser paints, so it never shows up in between.
  new MutationObserver(() => {
    if (showStashMarkerList) return;
    const view = document.getElementById(TIMELINE_ID);
    if (view && view.parentElement) hideStashMarkerList(view.parentElement);
  }).observe(document.body, { childList: true, subtree: true });

  // The Markers tab is only rendered when it's opened, and re-rendered by
  // Stash at times, so the view is put back whenever it's missing.
  let timelineCheckPending = false;
  new MutationObserver(() => {
    if (timelineCheckPending) return;
    timelineCheckPending = true;
    setTimeout(() => {
      timelineCheckPending = false;
      const panel = findMarkersPanel();
      const view = document.getElementById(TIMELINE_ID);
      if (panel && timelineMarkers.length && (!view || view.parentElement !== panel)) renderTimeline();
      // Stash redraws its list at times (e.g. after an edit): hide it again.
      else if (panel && view) hideStashMarkerList(panel);
    }, 200);
  }).observe(document.body, { childList: true, subtree: true });

  // -- edit form as an accordion under the marker's row --------------------------
  //
  // When a marker is edited from this plugin — its Edit button in the
  // timeline list, or a click on the marker on the scrubber — Stash's own
  // edit form is moved from the top of the Markers tab to right below that
  // marker's row, like an accordion.
  //
  // The form belongs to Stash's React UI, which expects it to stay where it
  // rendered it. So a placeholder marks its original spot, and the form is
  // put back there the moment Save, Cancel or Delete is used — before Stash
  // reacts to that click — and whenever this view is rebuilt. Otherwise
  // React, when it later removes the form, wouldn't find it where it left it.

  // The marker whose row should get the form, and when that was asked for.
  let accordionRequest = null; // { markerId, at }
  // The form while it's moved: { form, placeholder, holder, row }.
  let movedForm = null;

  function findStashMarkerForm(panel) {
    return Array.from(panel.querySelectorAll("form")).find(
      (f) => !f.closest(`#${TIMELINE_ID}`) && f.querySelector('[class*="react-select__control"]')
    ) || null;
  }

  function setRowOpen(row, open) {
    row.style.marginBottom = open ? "0" : "6px";
    row.style.borderBottomLeftRadius = open ? "0" : "4px";
    row.style.borderBottomRightRadius = open ? "0" : "4px";
    const edit = row.querySelector(".marker-symbols-edit");
    if (edit) edit.textContent = open ? "Close" : "Edit";
  }

  function restoreForm() {
    if (!movedForm) return;
    const { form, placeholder, holder, row } = movedForm;
    movedForm = null;
    if (placeholder.parentNode) {
      placeholder.parentNode.insertBefore(form, placeholder);
    } else {
      // Its original spot is gone (Stash re-rendered the tab), so React no
      // longer manages this form — just take it away.
      form.remove();
    }
    placeholder.remove();
    holder.remove();
    if (row.isConnected) setRowOpen(row, false);
    // A rebuild that waited for the form to close — after Stash has
    // handled the click that closed it.
    if (timelineRenderPending) setTimeout(renderTimeline, 0);
  }

  function moveFormUnder(form, row) {
    const placeholder = document.createComment("marker-symbols: Stash's marker form belongs here");
    form.parentNode.insertBefore(placeholder, form);
    const holder = document.createElement("div");
    holder.className = "marker-symbols-accordion";
    holder.style.cssText =
      "padding:12px;margin-bottom:6px;background:rgba(255,255,255,0.08);" +
      `border-left:${row.style.borderLeft ? row.style.borderLeft.split(" ").slice(0, 2).join(" ") : "4px solid"} ${row.style.borderLeftColor};` +
      "border-bottom-left-radius:4px;border-bottom-right-radius:4px;";
    row.after(holder);
    holder.appendChild(form);
    movedForm = { form, placeholder, holder, row };
    setRowOpen(row, true);
    scrollToTop(row);
  }

  // Asks for the form to open under `marker`'s row, if the timeline view
  // shows one. Called by openMarkerEditor.
  function requestAccordion(marker) {
    restoreForm();
    const row = document.querySelector(`#${TIMELINE_ID} [data-marker-id="${CSS.escape(String(marker.id))}"]`);
    // With a row: the form opens under it. Without: it opens in Stash's
    // usual place, and the sidebar just scrolls to it.
    accordionRequest = { markerId: row ? String(marker.id) : null, at: Date.now() };
  }

  // Scrolls the sidebar (and whatever else scrolls around it) so `el` sits
  // at the top — after the browser has laid the form out, so the scroll
  // lands where the form really is.
  function scrollToTop(el) {
    requestAnimationFrame(() => el.scrollIntoView({ block: "start", behavior: "smooth" }));
  }

  function syncAccordion() {
    if (movedForm) {
      // Stash re-rendered around it, or the page changed: tidy up.
      if (!movedForm.form.isConnected || !movedForm.placeholder.isConnected || !movedForm.row.isConnected) restoreForm();
      return;
    }
    if (!accordionRequest) return;
    if (Date.now() - accordionRequest.at > 5000) {
      accordionRequest = null; // the form never showed up
      return;
    }
    const panel = findMarkersPanel();
    const form = panel && findStashMarkerForm(panel);
    if (!form) return;
    const { markerId } = accordionRequest;
    const row = markerId && document.querySelector(`#${TIMELINE_ID} [data-marker-id="${CSS.escape(markerId)}"]`);
    accordionRequest = null;
    if (row) moveFormUnder(form, row); // scrolls the row to the top
    else scrollToTop(form);
  }

  // The form's Save, Cancel and Delete: put the form back before Stash's own
  // handler runs (Stash's handlers run as the event bubbles up; this runs on
  // the way down). Other buttons in the form — like setting the current
  // time — leave it where it is.
  const CLOSING_WORDS = /^(cancel|delete|close|abbrechen|löschen|schließen)$/i;
  function restoreBeforeStash(e) {
    if (!movedForm || !movedForm.form.contains(e.target)) return;
    if (e.type === "submit") {
      restoreForm();
      return;
    }
    const button = e.target.closest("button");
    if (!button) return;
    if (
      button.type === "submit" ||
      button.classList.contains("btn-primary") ||
      button.classList.contains("btn-danger") ||
      CLOSING_WORDS.test(button.textContent.trim())
    ) {
      restoreForm();
    }
  }
  document.addEventListener("click", restoreBeforeStash, true);
  document.addEventListener("submit", restoreBeforeStash, true);

  // The row's Edit button, while its form is open: close it with the form's
  // own Cancel, so Stash leaves edit mode too.
  function closeAccordion() {
    if (!movedForm) return false;
    const cancel = Array.from(movedForm.form.querySelectorAll("button")).find(
      (b) => b.type !== "submit" && !b.classList.contains("btn-danger") && CLOSING_WORDS.test(b.textContent.trim())
    ) || movedForm.form.querySelector("button.btn-secondary");
    if (cancel) cancel.click(); // restoreBeforeStash puts the form back first
    else restoreForm();
    return true;
  }

  let accordionCheckPending = false;
  new MutationObserver(() => {
    if (accordionCheckPending) return;
    accordionCheckPending = true;
    setTimeout(() => {
      accordionCheckPending = false;
      syncAccordion();
    }, 100);
  }).observe(document.body, { childList: true, subtree: true });

  // -- navigation wiring -------------------------------------------------

  function debounce(fn, ms) {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  }

  const scheduleRefresh = debounce(refreshForCurrentPage, 300);

  // -- tag bubble on hover -----------------------------------------------------
  //
  // Hovering a tag shows the bubble it gives a marker, next to the pointer:
  // options in the tag dropdown while a marker is being created or edited,
  // tags already picked in that form, and tag badges in the Markers tab's
  // list. Stash only shows tag *names* there, so each name is looked up
  // once to get the tag's image, then cached. A tag without an image (or
  // a name that isn't a tag, like a performer) shows nothing.

  const tagsByName = new Map(); // lowercased name → Promise<tag or null>

  function lookupTagByName(name) {
    const key = name.toLowerCase();
    if (!tagsByName.has(key)) {
      const query = `
        query($name: String!) {
          findTags(tag_filter: { name: { value: $name, modifier: EQUALS } }, filter: { per_page: 1 }) {
            tags { id name description image_path parents { id name } }
          }
        }`;
      tagsByName.set(key, callGQL(query, { name })
        .then((data) => data.findTags.tags[0] || null)
        .catch((err) => {
          console.warn(`[Marker Symbols] Couldn't look up tag "${name}":`, err);
          tagsByName.delete(key); // try again next time
          return null;
        }));
    }
    return tagsByName.get(key);
  }

  // The scene's Markers tab. Its pane id comes from react-bootstrap
  // ("…-tabpane-scene-markers-panel"); older layouts are matched by the
  // plain id or the active tab's label.
  function findMarkersPanel() {
    const panel =
      document.querySelector('[id$="tabpane-scene-markers-panel"]') ||
      document.getElementById("scene-markers-panel");
    if (panel) return panel;
    const activeTab = document.querySelector(".nav-tabs .nav-link.active");
    return activeTab && /marker/i.test(activeTab.textContent) ? document.querySelector(".tab-pane.active") : null;
  }

  // What counts as "a tag" to hover: react-select options and picked
  // values (Stash's tag pickers), and Stash's tag badges.
  const HOVER_TARGETS =
    '[class*="react-select__option"], [class*="react-select__multi-value"], ' +
    '[class*="react-select__single-value"], .tag-item';

  // Only in the marker context: inside the Markers tab, or — since the
  // dropdown's option list can be rendered elsewhere in the page — while
  // a field inside the Markers tab has focus.
  function inMarkerContext(el) {
    const panel = findMarkersPanel();
    if (!panel) return false;
    return panel.contains(el) || panel.contains(document.activeElement);
  }

  function hoveredTagName(el) {
    const label = el.querySelector('[class*="multi-value__label"]');
    return ownText(label || el);
  }

  // An element's text without the parent-tag hint this plugin adds to
  // dropdown options (see annotateTagOptions), so names still match.
  function ownText(el) {
    let text = "";
    el.childNodes.forEach((node) => {
      if (node.nodeType === 1 && node.classList.contains("marker-symbols-parents")) return;
      text += node.textContent;
    });
    return text.trim();
  }

  let hoverTarget = null;
  let hoverBubble = null;

  function hideTagBubble() {
    if (hoverBubble) hoverBubble.remove();
    hoverBubble = null;
    hoverTarget = null;
  }

  async function showTagBubble(target) {
    hoverTarget = target;
    const name = hoveredTagName(target);
    const tag = name ? await lookupTagByName(name) : null;
    // The pointer may have moved on while the lookup ran.
    if (hoverTarget !== target || !target.isConnected) return;
    let bubble = tag && makeMarkerIcons({ primary_tag: tag, tags: [], seconds: 0 }, null, { preview: true });
    const description = ((tag && tag.description) || "").trim();
    if (!bubble && description) {
      // No image, but a description worth showing: a plain bubble for it.
      bubble = document.createElement("div");
      bubble.className = "marker-symbols-bubble";
      bubble.style.cssText =
        "display:inline-flex;flex-direction:column;padding:3px 4px;background:rgba(255,255,255,0.92);" +
        `border-radius:${BUBBLE_RADIUS_PX}px;box-shadow:0 2px 6px rgba(0,0,0,0.55);`;
    }
    if (!bubble) return;
    if (description) {
      // Under the image: the tag's description, cut off after a few lines
      // so a long one doesn't cover the page.
      const text = document.createElement("div");
      text.className = "marker-symbols-description";
      text.textContent = description;
      text.style.cssText = [
        "max-width:280px",
        "margin-top:4px",
        "color:#222",
        "font-size:12px",
        "line-height:1.35",
        "text-align:left",
        "white-space:pre-line",
        "overflow:hidden",
        "display:-webkit-box",
        "-webkit-box-orient:vertical",
        "-webkit-line-clamp:8",
      ].join(";");
      bubble.appendChild(text);
    }

    if (hoverBubble) hoverBubble.remove();
    bubble.style.position = "fixed";
    bubble.style.zIndex = "5000";
    bubble.style.pointerEvents = "none";
    // Beside the tag, vertically centered on it — to the right, or to the
    // left when there's no room on the right.
    const r = target.getBoundingClientRect();
    bubble.style.top = `${r.top + r.height / 2}px`;
    bubble.style.transform = "translateY(-50%)";
    document.body.appendChild(bubble);
    const width = bubble.getBoundingClientRect().width;
    const left = r.right + 8 + width <= window.innerWidth ? r.right + 8 : r.left - 8 - width;
    bubble.style.left = `${Math.max(4, left)}px`;
    hoverBubble = bubble;
  }

  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest ? e.target.closest(HOVER_TARGETS) : null;
    // Picked values nest a label inside the value itself — treat the pair
    // as one target.
    const target = el && (el.parentElement && el.parentElement.closest('[class*="react-select__multi-value"]')) || el;
    if (target === hoverTarget) return;
    hideTagBubble();
    if (target && inMarkerContext(target)) showTagBubble(target);
  });
  // Scrolling or clicking moves things out from under the bubble.
  document.addEventListener("scroll", hideTagBubble, true);
  document.addEventListener("mousedown", hideTagBubble, true);

  // -- parent tags in the marker form's tag dropdown ----------------------------
  //
  // Stash's tag dropdown only lists names, so tags with the same kind of
  // name ("Solo" under Violin, "Solo" under Piano) or a whole family of
  // sub-tags are hard to tell apart. This adds each option's parent tags
  // after its name, greyed out: "Violin (Strings)". Only in the marker
  // context (see inMarkerContext), and only for names that are real tags.

  async function annotateOption(option) {
    const name = ownText(option);
    if (!name || option.dataset.markerSymbolsParentsFor === name) return;
    option.dataset.markerSymbolsParentsFor = name;
    const old = option.querySelector(".marker-symbols-parents");
    if (old) old.remove();

    const tag = await lookupTagByName(name);
    // The option may show another tag by now (React reuses option
    // elements while you type), in which case that one gets its own pass.
    if (!tag || !option.isConnected || ownText(option) !== name) return;
    const parents = (tag.parents || []).map((p) => p.name).sort((a, b) => a.localeCompare(b));
    if (!parents.length) return;
    const hint = document.createElement("span");
    hint.className = "marker-symbols-parents";
    hint.style.cssText = "margin-left:6px;opacity:0.6;font-size:0.85em;";
    hint.textContent = `(${parents.join(", ")})`;
    option.appendChild(hint);
  }

  function annotateTagOptions() {
    document.querySelectorAll('[class*="react-select__option"]').forEach((option) => {
      if (inMarkerContext(option)) annotateOption(option);
    });
  }

  // The dropdown's options appear, change as you type and disappear again,
  // so this watches the page and re-checks at most every 150ms.
  let optionsCheckPending = false;
  new MutationObserver(() => {
    if (optionsCheckPending) return;
    optionsCheckPending = true;
    setTimeout(() => {
      optionsCheckPending = false;
      annotateTagOptions();
    }, 150);
  }).observe(document.body, { childList: true, subtree: true, characterData: true });

  // -- reload after a marker is saved ----------------------------------------
  //
  // Stash's own UI saves markers through GraphQL mutations over fetch().
  // Wrapping fetch lets this notice a marker being created, updated or
  // deleted — from the edit form, the Markers tab, anywhere — and redraw
  // every bubble with fresh data once it succeeded. The longer delay gives
  // Stash time to redraw its own marker ranges first.
  const MARKER_MUTATION = /\bsceneMarkers?\w*(Create|Update|Destroy)\b/i;
  const scheduleMarkerReload = debounce(refreshForCurrentPage, 800);

  if (typeof window.fetch === "function" && !window.fetch.__markerSymbolsWrapped) {
    const originalFetch = window.fetch;
    const wrappedFetch = function (input, init) {
      const result = originalFetch.apply(this, arguments);
      const body = init && init.body;
      if (typeof body === "string" && body.includes("mutation") && MARKER_MUTATION.test(body)) {
        result.then((r) => { if (r.ok) scheduleMarkerReload(); }).catch(() => {});
      }
      return result;
    };
    wrappedFetch.__markerSymbolsWrapped = true;
    window.fetch = wrappedFetch;
  }

  // Backup in case a Stash version sends those requests some other way:
  // when the scrubber's marker ranges change (one added, removed or moved
  // to a new time), reload too. Compared by count and position, so our own
  // bubbles being mounted into those ranges doesn't count as a change.
  //
  // It also catches everything else that leaves the scrubber without
  // bubbles, by comparing what's on screen with the last time they were
  // mounted (see mountIconsOnMarkerRanges):
  //   - the ranges differ from then: added, removed, moved, or appearing
  //     only now — e.g. on a phone, where the player often doesn't load
  //     the video (and so draws no ranges) until you tap play, long after
  //     the placement retries gave up;
  //   - the ranges are the same, but Stash redrew them after an edit and
  //     our bubbles went with the old ones.
  // Each situation asks for one reload, so a state that doesn't settle
  // can't keep reloading.
  let lastReloadRequest = null;
  function requestReload(reason) {
    if (reason === lastReloadRequest) return;
    lastReloadRequest = reason;
    scheduleMarkerReload();
  }
  // The player rewrites inline styles several times a second while
  // playing, so the check runs at most every 250ms however often this fires.
  let rangeCheckPending = false;
  new MutationObserver(() => {
    if (rangeCheckPending) return;
    rangeCheckPending = true;
    setTimeout(() => {
      rangeCheckPending = false;
      if (!currentSceneId()) return;
      const signature = rangeSignature();
      if (!signature) return; // no ranges (yet): nothing to put bubbles on
      if (signature !== lastMountSignature) {
        requestReload(`ranges:${signature}`);
      } else if (mountedIcons.some((el) => !el.isConnected)) {
        requestReload(`lost:${mountGeneration}`);
      }
    }, 250);
  }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["style"] });

  if (window.PluginApi && window.PluginApi.Event && typeof window.PluginApi.Event.addEventListener === "function") {
    window.PluginApi.Event.addEventListener("stash:location", scheduleRefresh);
    scheduleRefresh();
  } else {
    scheduleRefresh();
    const observer = new MutationObserver(scheduleRefresh);
    observer.observe(document.body, { childList: true, subtree: true });
  }
})();
