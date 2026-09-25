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

  const ICON_SIZE_PX = 44;
  // Corner rounding of the bubble and of each image in it. 0 = square.
  const BUBBLE_RADIUS_PX = 0;
  const ICON_RADIUS_PX = 0;
  const MARKER_RANGE_SELECTOR = ".vjs-marker-range";
  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "markerImprovements";

  const MAX_PLACEMENT_RETRIES = 20;
  const PLACEMENT_RETRY_MS = 500;

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

  async function fetchMarkers(sceneId) {
    const query = `
      query($id: ID!) {
        findScene(id: $id) {
          scene_markers {
            id
            seconds
            title
            primary_tag { id name image_path }
            tags { id name image_path }
          }
        }
      }`;
    const data = await callGQL(query, { id: sceneId });
    return data.findScene.scene_markers || [];
  }

  // This plugin's settings (Settings > Plugins), as saved. Read fresh on
  // every scene load, so a change shows up on the next one. Settings never
  // touched are simply missing, which is why the click-to-edit one is a
  // "disable" switch: missing = off = editing enabled.
  async function fetchPluginSettings() {
    try {
      const data = await callGQL(`query { configuration { plugins } }`);
      return (data.configuration.plugins || {})[PLUGIN_ID] || {};
    } catch (err) {
      console.warn("[Marker Symbols] Couldn't read plugin settings:", err);
      return {};
    }
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

  function findVideoEl() {
    return document.querySelector("video");
  }

  // -- state / cleanup --------------------------------------------------

  // Every icon-group element we've appended into a .vjs-marker-range, so
  // clearOverlay() can remove just those without touching Stash's own
  // marker-range elements themselves.
  let mountedIcons = [];
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
  // Whether clicking a marker's range or icon opens Stash's marker editor
  // (the "Don't open the marker editor on click" setting, inverted).
  let editOnClick = true;
  // Every marker paired with its .vjs-marker-range on the current mount —
  // including markers without an icon — for the range click handler.
  let tickPairs = [];

  function clearOverlay() {
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
  function makeMarkerIcons(marker, video) {
    const tags = tagsWithImages(marker);
    if (tags.length === 0) return null;

    const primaryName = (marker.primary_tag && marker.primary_tag.name) || "";
    const baseLabel = `${formatTime(marker.seconds)} — ${marker.title || primaryName || "marker"}`;

    const bubble = document.createElement("div");
    bubble.className = "marker-symbols-bubble";
    bubble.style.cssText = [
      "position:absolute",
      "left:50%",
      "bottom:100%",
      "transform:translateX(-50%)",
      "margin-bottom:6px",
      "display:flex",
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
      "background:rgba(255,255,255,0.92)",
      "transform:rotate(45deg)",
      "pointer-events:none",
    ].join(";");
    bubble.appendChild(tail);

    const jumpToMarker = (e) => {
      e.stopPropagation();
      e.preventDefault();
      video.currentTime = marker.seconds;
      if (editOnClick) openMarkerEditor(marker);
    };

    tags.forEach((tag) => {
      const label = tag.name ? `${baseLabel} (${tag.name})` : baseLabel;
      const img = document.createElement("img");
      img.src = tag.image_path;
      img.alt = tag.name || "marker";
      img.dataset.tagName = tag.name || "";
      img.title = label;
      img.style.cssText = [
        "cursor:pointer", "user-select:none", "flex:none",
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
        "mix-blend-mode:multiply",
      ].join(";");
      img.addEventListener("click", jumpToMarker);
      // If this particular tag's image fails to load, just drop it — the
      // marker's other tag images (if any) are unaffected.
      img.addEventListener("error", () => img.remove());
      bubble.appendChild(img);
    });

    if (tags.length > 1) removeDuplicateImages(bubble);

    return bubble;
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
  // .vjs-marker-range elements — and applies the "Custom styles per tag"
  // setting to its icon(s).
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

    // Custom styles from the plugin setting go on last, so they can
    // override the icon's built-in styles (see makeMarkerIcons).
    // A rule matches every tag whose name contains its text, so `Violin`
    // also styles "Violin I" and "Solo Violin". `*` goes first; the rest
    // follow in the order they're written, so a later rule wins where two
    // match the same icon and set the same property.
    iconGroupEl.querySelectorAll("img").forEach((img) => {
      const tagName = (img.dataset.tagName || "").toLowerCase();
      const star = tagStyles.get("*");
      if (star) img.style.cssText += `;${star}`;
      tagStyles.forEach((css, key) => {
        if (key !== "*" && tagName.includes(key)) img.style.cssText += `;${css}`;
      });
    });

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

  // Pairs every .vjs-marker-range found (sorted left-to-right) against
  // every marker from Stash (sorted by timestamp), index for index, and
  // mounts each marker's icon(s) into its matched element.
  function mountIconsOnMarkerRanges(video, markers) {
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
    if (!markers.length) return;

    const root = video.closest(".video-js, .vjs-container") || document;
    if (!findMarkerRangeElements(root).length) {
      // Stash hasn't drawn its marker-range elements yet (player still
      // initializing) — wait and try again rather than giving up.
      retryPlacement(sceneId, attempt);
      return;
    }

    lastMarkers = markers;
    tagStyles = parseTagStyles(settings.tagStyles || "");
    editOnClick = !settings.disableEditOnClick;
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
    const sceneId = currentSceneId();
    if (!sceneId) return;
    placeSymbols(sceneId, 0);
  }

  // -- navigation wiring -------------------------------------------------

  function debounce(fn, ms) {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  }

  const scheduleRefresh = debounce(refreshForCurrentPage, 300);

  if (window.PluginApi && window.PluginApi.Event && typeof window.PluginApi.Event.addEventListener === "function") {
    window.PluginApi.Event.addEventListener("stash:location", scheduleRefresh);
    scheduleRefresh();
  } else {
    scheduleRefresh();
    const observer = new MutationObserver(scheduleRefresh);
    observer.observe(document.body, { childList: true, subtree: true });
  }
})();
