// Marker Improvements — UI addon
//
// For each scene marker, shows one small image per tag on it that has a
// real custom image uploaded (Settings on a tag page lets you upload
// one) — mounted directly inside Stash's own colored marker indicator on
// the video scrubber (class `.vjs-marker-range`, one per marker) and
// tinted to match its color. Hidden until that specific indicator is
// hovered, actively dragged/touched, or keyboard-focused. Click an icon
// to jump straight to that marker.
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
//   logMarkerImagePlan() prints a console.table of every marker's tags
//   and whether each qualifies for an icon — check that against what
//   actually renders when something looks off. The scrubber-rendering
//   summary line (see mountIconsOnMarkerRanges) says how many
//   `.vjs-marker-range` elements were found vs. how many markers came
//   back from Stash, and how many icons actually got mounted.
//
// A tag with no custom image still returns a non-empty `image_path` from
// Stash — it just points at Stash's own generic placeholder, marked with
// a `default=true` query param (the same convention Stash uses for
// performers/studios). hasCustomImage() filters those out, so a tag with
// no real image just doesn't get an icon rather than showing a generic
// placeholder for every tag.

(function () {
  "use strict";

  const ICON_SIZE_PX = 22;
  const MARKER_RANGE_SELECTOR = ".vjs-marker-range";

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
  // {target, type, handler} for every listener wireVisibility() registered
  // (some on `document`, not just a marker-range element), so
  // clearOverlay() can undo all of them without a fixed set of variables.
  let visibilityListeners = [];
  // {el, prop, original} for every inline overflow style unclipAncestors()
  // overrode, so clearOverlay() can put each one back exactly as found.
  let overflowOverrides = [];

  function clearOverlay() {
    mountedIcons.forEach((el) => el.remove());
    mountedIcons = [];
    visibilityListeners.forEach(({ target, type, handler }) => target.removeEventListener(type, handler));
    visibilityListeners = [];
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

  // A marker's primary tag plus its other tags, deduped — unfiltered, so
  // both tagsWithImages() and logMarkerImagePlan() (which needs to show
  // excluded tags too, not just the ones that qualify) share one
  // definition of "this marker's tags" instead of drifting apart.
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
    return dedupedTags(marker).filter(hasCustomImage);
  }

  // Logs a table of every marker's tags and whether each one qualifies
  // for an icon, so what's actually fetched/decided can be checked
  // against what's on screen without guessing.
  function logMarkerImagePlan(markers) {
    const rows = [];
    markers.forEach((marker) => {
      const label = marker.title || (marker.primary_tag && marker.primary_tag.name) || `marker ${marker.id}`;
      const markerLabel = `${formatTime(marker.seconds)} ${label}`;
      const tags = dedupedTags(marker);
      if (tags.length === 0) {
        rows.push({ marker: markerLabel, tag: "(no tags)", "will show icon": false, image_path: "" });
        return;
      }
      tags.forEach((tag) => {
        rows.push({
          marker: markerLabel,
          tag: tag.name,
          "will show icon": hasCustomImage(tag),
          image_path: tag.image_path || "(none)",
        });
      });
    });
    console.info(
      `[Marker Symbols] Tag image plan — ${markers.length} marker(s), ${rows.length} tag row(s). ` +
      '"will show icon": false means that tag has no custom image (just Stash\'s default ' +
      "placeholder, filtered out) — it's excluded on purpose, not a bug."
    );
    console.table(rows);
  }

  // Builds the little cluster of icons for one marker: one image per tag
  // on it that has an image uploaded (primary tag included). Returns null
  // if none of its tags have an image — that marker just gets no icon,
  // rather than a generic placeholder. Always mounted at the very start
  // (left:0%) of whatever .vjs-marker-range it ends up inside, since a
  // "range" extends rightward from the marker's own timestamp — its own
  // translate(-50%,-50%) centers the icon symmetrically over that point.
  function makeMarkerIcons(marker, video) {
    const tags = tagsWithImages(marker);
    if (tags.length === 0) return null;

    const primaryName = (marker.primary_tag && marker.primary_tag.name) || "";
    const baseLabel = `${formatTime(marker.seconds)} — ${marker.title || primaryName || "marker"}`;

    const group = document.createElement("div");
    group.style.cssText = [
      "position:absolute",
      "left:0",
      "top:50%",
      "transform:translate(-50%,-50%)",
      "display:flex",
      "align-items:center",
      "gap:2px",
      "opacity:0",
      "pointer-events:none",
      "transition:opacity 0.15s ease",
    ].join(";");

    const jumpToMarker = (e) => {
      e.stopPropagation();
      e.preventDefault();
      video.currentTime = marker.seconds;
    };

    tags.forEach((tag) => {
      const label = tag.name ? `${baseLabel} (${tag.name})` : baseLabel;
      const img = document.createElement("img");
      img.src = tag.image_path;
      img.alt = tag.name || "marker";
      img.title = label;
      img.style.cssText = [
        "cursor:pointer", "user-select:none", "flex:none",
        `width:${ICON_SIZE_PX}px`,
        `height:${ICON_SIZE_PX}px`,
        "object-fit:cover",
        "border-radius:4px",
        "border:1px solid rgba(255,255,255,0.85)",
        "box-shadow:0 0 4px rgba(0,0,0,0.85)",
      ].join(";");
      img.addEventListener("click", jumpToMarker);
      // If this particular tag's image fails to load, just drop it — the
      // marker's other tag images (if any) are unaffected.
      img.addEventListener("error", () => img.remove());
      group.appendChild(img);
    });

    return group;
  }

  // Shows every element in `groups` on hover, but also while `container`
  // is actively being used: mouse/touch held down (which can continue
  // after the pointer leaves the element itself — mouseup/touchend are
  // watched on the whole document so it doesn't get stuck visible), or
  // keyboard-focused. Touch devices have no hover at all, so without the
  // touch handling here the icons would never show up on them. Each
  // group's opacity/pointer-events are set directly (rather than relying
  // on CSS inheritance) since `groups` can span multiple containers.
  function wireVisibility(container, groups) {
    let hovering = false;
    let active = false;

    const sync = () => {
      const visible = hovering || active;
      groups.forEach((el) => {
        el.style.opacity = visible ? "1" : "0";
        el.style.pointerEvents = visible ? "auto" : "none";
      });
    };
    const onEnter = () => { hovering = true; sync(); };
    const onLeave = () => { hovering = false; sync(); };
    const onActivate = () => { active = true; sync(); };
    const onDeactivate = () => { active = false; sync(); };

    const bind = (target, type, handler, opts) => {
      target.addEventListener(type, handler, opts);
      visibilityListeners.push({ target, type, handler });
    };

    bind(container, "mouseenter", onEnter);
    bind(container, "mouseleave", onLeave);
    bind(container, "mousedown", onActivate);
    bind(container, "touchstart", onActivate, { passive: true });
    bind(container, "focus", onActivate);
    bind(container, "blur", onDeactivate);
    bind(document, "mouseup", onDeactivate);
    bind(document, "touchend", onDeactivate);
    bind(document, "touchcancel", onDeactivate);
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
  // .vjs-marker-range elements — and tints its icon(s) with that
  // element's own color so they read as part of the colored bar rather
  // than something dropped on top of it.
  function mountIconOnTick(tick, iconGroupEl, unclipRoot) {
    const computed = getComputedStyle(tick);
    if (computed.position === "static") {
      overflowOverrides.push({ el: tick, prop: "position", original: tick.style.position });
      tick.style.position = "relative";
    }
    unclipAncestors(tick, unclipRoot);

    const tickColor = computed.backgroundColor;
    if (tickColor && tickColor !== "rgba(0, 0, 0, 0)" && tickColor !== "transparent") {
      iconGroupEl.querySelectorAll("img").forEach((img) => {
        img.style.borderColor = tickColor;
        img.style.boxShadow = `0 0 4px ${tickColor}`;
      });
    }

    tick.appendChild(iconGroupEl);
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

    let mountedCount = 0;
    for (let i = 0; i < pairCount; i++) {
      const iconGroup = makeMarkerIcons(sortedMarkers[i], video);
      if (!iconGroup) continue;
      mountIconOnTick(ticks[i], iconGroup, root);
      wireVisibility(ticks[i], [iconGroup]);
      mountedIcons.push(iconGroup);
      mountedCount++;
    }

    console.info(
      `[Marker Symbols] Mounted ${mountedCount} icon(s) directly onto ${MARKER_RANGE_SELECTOR} ` +
      `containers (${ticks.length} found for ${sortedMarkers.length} marker(s) with data).`
    );
  }

  async function placeSymbols(sceneId, attempt) {
    attempt = attempt || 0;
    const video = findVideoEl();
    if (!video) {
      retryPlacement(sceneId, attempt);
      return;
    }

    let markers;
    try {
      markers = await fetchMarkers(sceneId);
    } catch (err) {
      console.error("[Marker Symbols] Failed to fetch markers:", err);
      return;
    }
    if (currentSceneId() !== sceneId) return; // navigated away while fetching
    if (!markers.length) return;

    logMarkerImagePlan(markers);

    const root = video.closest(".video-js, .vjs-container") || document;
    if (!findMarkerRangeElements(root).length) {
      // Stash hasn't drawn its marker-range elements yet (player still
      // initializing) — wait and try again rather than giving up.
      retryPlacement(sceneId, attempt);
      return;
    }

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
