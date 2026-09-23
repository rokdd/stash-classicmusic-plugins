// Marker Improvements — UI addon
//
// Overlays each scene marker's tag image on the video scrubber (seek bar)
// at that marker's timestamp — hidden until the scrubber is hovered,
// actively dragged/touched, or keyboard-focused, so it doesn't clutter
// the player otherwise. Click an icon to jump straight to that marker.
//
// How it finds the scrubber:
//   Stash's player's internal markup can differ by version, so rather than
//   depending on one exact element, this script tries a short list of
//   known scrubber/progress-bar selectors (SCRUBBER_SELECTORS below). If
//   none match on your version, it falls back to drawing its own thin bar
//   directly under the video instead (still clickable, still positioned
//   correctly, still hover-to-reveal — just not on Stash's own control
//   bar). The console says which one is active — see placeSymbols().
//   If you want it precisely on your real scrubber and the fallback bar
//   is showing instead, open devtools on a scene page, find the element
//   that is the actual seek/progress bar, and add its selector to
//   SCRUBBER_SELECTORS.
//
//   When the real scrubber IS found, the icons are appended as actual
//   children of it — not a separately-positioned overlay layered on top —
//   so they're truly part of the seek bar's own DOM, positioned by
//   percentage along it based on each marker's timestamp. Since the real
//   track is usually only a few px tall (and sometimes clips its content
//   with overflow:hidden for a rounded look), unclipAncestors() forces
//   `overflow: visible` on the scrubber and any clipping ancestor up to
//   the player, so a 22px icon isn't cut down to an invisible sliver by a
//   track a fraction of that height.
//
//   Stash draws its own small colored marker indicator per marker
//   (class `.vjs-marker-range`) on the scrubber, tinted with that
//   marker's tag color. When NATIVE_MARKER_SELECTORS finds one at
//   (roughly) the same position as a marker — see findClosestTick — that
//   marker's icon is mounted directly inside it and tinted to match its
//   color, instead of floating separately in our own overlay. A marker
//   with no matching indicator still gets positioned by percentage in the
//   overlay as before, so nothing silently disappears.
//
// Icons:
//   Shows one icon per tag on the marker that actually has an image
//   uploaded (Settings on a tag page lets you upload one) — the primary
//   tag and any other tags on that marker — clustered together at that
//   marker's position. A marker with no tag images at all gets no icon.

(function () {
  "use strict";

  const ICON_SIZE_PX = 22;

  const SCRUBBER_SELECTORS = [
    ".vjs-progress-control .vjs-progress-holder",
    ".vjs-progress-control",
    ".video-js .vjs-progress-holder",
    ".vjs-control-bar .vjs-progress-holder",
    // Broader fallbacks for player markup that doesn't match any of the
    // known video.js class names above (a custom skin, a different major
    // version, etc.) — matched last, only if none of the specific
    // selectors above found anything.
    '[class*="progress-holder"]',
    '[class*="seek-bar"]',
    '[class*="scrubber"]',
  ];

  // Stash's own small colored marker indicators on the scrubber — one per
  // scene marker, tinted with that marker's tag color. `.vjs-marker-range`
  // is the confirmed class; the rest are fallback guesses in case it
  // changes in a future Stash version. Tried in order, scoped to inside
  // the scrubber only, so a guess here can't match something unrelated
  // elsewhere on the page.
  const NATIVE_MARKER_SELECTORS = [
    ".vjs-marker-range",
    ".vjs-marker",
    '[class*="marker-range"]',
  ];

  // How close (as a % of the scrubber's width) a native marker indicator's
  // own position has to be to a marker's computed position to count as a
  // match. Both are derived from the same seconds/duration formula, so a
  // genuine match should land far closer than this in practice.
  const TICK_MATCH_TOLERANCE_PCT = 2;

  const MAX_PLACEMENT_RETRIES = 20;
  const PLACEMENT_RETRY_MS = 500;

  // -- GraphQL -----------------------------------------------------------

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

  // -- helpers -------------------------------------------------------

  function currentSceneId() {
    const match = window.location.pathname.match(/\/scenes\/(\d+)/);
    return match ? match[1] : null;
  }

  function formatTime(seconds) {
    const s = Math.floor(seconds % 60).toString().padStart(2, "0");
    const m = Math.floor(seconds / 60);
    return `${m}:${s}`;
  }

  function findScrubber() {
    for (const selector of SCRUBBER_SELECTORS) {
      const el = document.querySelector(selector);
      if (el) return el;
    }
    return null;
  }

  function findVideoEl() {
    return document.querySelector("video");
  }

  // -- overlay rendering -----------------------------------------------

  let overlayEl = null;
  let placementTimer = null;
  // {target, type, handler} for every listener wireVisibility() registered
  // (some on `document`, not just the scrubber), so clearOverlay() can
  // undo all of them without needing a fixed set of named variables.
  let visibilityListeners = [];
  // {el, prop, original} for every inline overflow style unclipAncestors()
  // overrode, so clearOverlay() can put each one back exactly as found.
  let overflowOverrides = [];

  function clearOverlay() {
    if (overlayEl) {
      overlayEl.remove();
      overlayEl = null;
    }
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

  // A marker's primary tag plus its other tags, deduped, filtered down to
  // just the ones that actually have an image uploaded — these are what
  // get shown for that marker (see makeMarkerIcons below).
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

  function tagsWithImages(marker) {
    const seen = new Set();
    const result = [];
    const consider = (tag) => {
      if (!hasCustomImage(tag)) return;
      const key = tag.id != null ? `id:${tag.id}` : `name:${tag.name}`;
      if (seen.has(key)) return;
      seen.add(key);
      result.push(tag);
    };
    consider(marker.primary_tag);
    (marker.tags || []).forEach(consider);
    return result;
  }

  // Builds the little cluster of icons shown at one marker's position: one
  // image per tag on that marker that has an image uploaded (primary tag
  // included). Returns null if none of its tags have an image — that
  // marker just gets no icon, rather than a generic placeholder. Returns
  // { el, pct } otherwise — `pct` (position along the scrubber, 0-100) is
  // exposed so a caller can match this marker against a native marker
  // indicator at roughly the same position (see findClosestTick below).
  function makeMarkerIcons(marker, duration, video) {
    const tags = tagsWithImages(marker);
    if (tags.length === 0) return null;

    const pct = Math.min(100, Math.max(0, (marker.seconds / duration) * 100));
    const primaryName = (marker.primary_tag && marker.primary_tag.name) || "";
    const baseLabel = `${formatTime(marker.seconds)} — ${marker.title || primaryName || "marker"}`;

    const group = document.createElement("div");
    group.style.cssText = [
      "position:absolute",
      `left:${pct}%`,
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

    return { el: group, pct };
  }

  // Shows every element in `groups` on hover, but also while the scrubber
  // is actively being used: mouse/touch held down for a seek-drag (which
  // can continue after the pointer leaves the bar itself — mouseup/
  // touchend are watched on the whole document so it doesn't get stuck
  // visible), or keyboard-focused. Touch devices have no hover at all, so
  // without the touch handling here the icons would never show up on
  // them. Each group's opacity/pointer-events are set directly (rather
  // than relying on CSS inheritance from one shared parent) since groups
  // mounted onto Stash's own native marker ticks live under a different
  // parent than the ones left floating in our own overlay.
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

  // Many players' real scrubber/progress track — and sometimes an ancestor
  // of it too — clips its content (overflow:hidden), usually just to keep
  // the rounded-corner track/fill looking tidy. A 22px icon actually
  // appended *inside* that track would get silently cut down to an
  // invisible sliver by that. Rather than working around it with a
  // separately-positioned overlay, this walks up from `scrubber` to `stop`
  // (inclusive) and forces `overflow: visible` on anything found clipping,
  // so the icons can be true DOM children of the real scrubber and still
  // show up poking slightly above/below its own thin box. Original values
  // are recorded in `overflowOverrides` for clearOverlay() to restore.
  function unclipAncestors(scrubber, stop) {
    let node = scrubber;
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

  // Finds Stash's own native per-marker indicators on the scrubber, if
  // any — scoped to inside `scrubber` only, so a broad guess here can't
  // match something unrelated elsewhere on the page.
  // Finds Stash's own native per-marker indicators on the scrubber, if
  // any — scoped to inside `scrubber` only, so a broad guess here can't
  // match something unrelated elsewhere on the page.
  function findNativeMarkerTicks(scrubber) {
    for (const selector of NATIVE_MARKER_SELECTORS) {
      const found = Array.from(scrubber.querySelectorAll(selector));
      if (found.length) return found;
    }
    return [];
  }

  // Which of `ticks` sits at roughly `pct` along `scrubber` — both should
  // land at (very close to) the same position, since both are derived
  // from the same seconds/duration formula. Returns null if the closest
  // one still isn't within TICK_MATCH_TOLERANCE_PCT.
  function findClosestTick(ticks, scrubber, pct) {
    const scrubberRect = scrubber.getBoundingClientRect();
    if (!scrubberRect.width) return null;
    let best = null;
    let bestDelta = Infinity;
    ticks.forEach((tick) => {
      const r = tick.getBoundingClientRect();
      const tickPct = ((r.left + r.width / 2 - scrubberRect.left) / scrubberRect.width) * 100;
      const delta = Math.abs(tickPct - pct);
      if (delta < bestDelta) {
        bestDelta = delta;
        best = tick;
      }
    });
    return bestDelta <= TICK_MATCH_TOLERANCE_PCT ? best : null;
  }

  // Mounts `iconGroupEl` as an actual child of `tick` — Stash's own native
  // marker indicator (`.vjs-marker-range`) — instead of leaving it
  // floating in our overlay, and tints its icon(s) with that indicator's
  // own color so they read as part of the colored bar rather than
  // something dropped on top of it.
  function mountIconOnTick(tick, iconGroupEl) {
    const computed = getComputedStyle(tick);
    if (computed.position === "static") {
      overflowOverrides.push({ el: tick, prop: "position", original: tick.style.position });
      tick.style.position = "relative";
    }
    if (computed.overflow === "hidden" || computed.overflow === "clip") {
      overflowOverrides.push({ el: tick, prop: "overflow", original: tick.style.overflow });
      tick.style.overflow = "visible";
    }
    // Re-anchor to the tick's own (usually tiny) box instead of the
    // percentage position computed against the whole scrubber.
    iconGroupEl.style.left = "50%";

    const tickColor = computed.backgroundColor;
    if (tickColor && tickColor !== "rgba(0, 0, 0, 0)" && tickColor !== "transparent") {
      iconGroupEl.querySelectorAll("img").forEach((img) => {
        img.style.borderColor = tickColor;
        img.style.boxShadow = `0 0 4px ${tickColor}`;
      });
    }

    tick.appendChild(iconGroupEl);
  }

  function renderOnScrubber(scrubber, video, markers) {
    const computed = getComputedStyle(scrubber);
    if (computed.position === "static") {
      scrubber.style.position = "relative";
    }

    const player = scrubber.closest(".video-js, .vjs-container") || scrubber.parentElement;
    unclipAncestors(scrubber, player);

    // Positioning container for whichever icon groups don't end up
    // matched to a native marker tick below.
    overlayEl = document.createElement("div");
    overlayEl.id = "marker-symbols-overlay";
    overlayEl.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;z-index:20;";
    scrubber.appendChild(overlayEl);

    const nativeTicks = findNativeMarkerTicks(scrubber);
    const groups = [];
    let mountedOnTicks = 0;

    markers.forEach((marker) => {
      const result = makeMarkerIcons(marker, video.duration, video);
      if (!result) return;
      const tick = nativeTicks.length ? findClosestTick(nativeTicks, scrubber, result.pct) : null;
      if (tick) {
        mountIconOnTick(tick, result.el);
        mountedOnTicks++;
      } else {
        overlayEl.appendChild(result.el);
      }
      groups.push(result.el);
    });

    wireVisibility(scrubber, groups);
    console.info(
      `[Marker Symbols] Rendering directly on the real scrubber (${mountedOnTicks}/${groups.length} ` +
      "icon(s) mounted onto Stash's own .vjs-marker-range indicators):",
      scrubber
    );
  }

  function buildOverlay(markers, duration, video) {
    const el = document.createElement("div");
    el.id = "marker-symbols-overlay";
    el.style.cssText = "position:absolute;left:0;top:0;width:100%;height:100%;z-index:20;";
    const groups = [];
    markers.forEach((m) => {
      const result = makeMarkerIcons(m, duration, video);
      if (!result) return;
      el.appendChild(result.el);
      groups.push(result.el);
    });
    return { el, groups };
  }

  function renderFallbackBar(video, markers) {
    // Guaranteed-to-work fallback: a thin bar directly under the video,
    // used only if none of SCRUBBER_SELECTORS matched. No native marker
    // indicators to mount onto here since this isn't Stash's own bar.
    console.warn(
      "[Marker Symbols] No known scrubber selector matched this player — falling back to a thin bar " +
      "under the video instead of hovering on Stash's own seek bar. If you want it merged into your " +
      "real scrubber, open devtools, find its element, and add its selector to SCRUBBER_SELECTORS " +
      "near the top of marker-symbols.js."
    );
    const player = video.closest(".video-js, .vjs-container") || video.parentElement;
    if (!player) return;

    const computed = getComputedStyle(player);
    if (computed.position === "static") {
      player.style.position = "relative";
    }

    const bar = document.createElement("div");
    bar.id = "marker-symbols-fallback-bar";
    bar.title = "Marker Symbols: couldn't find this player's real scrubber, showing markers here instead";
    bar.style.cssText = [
      "position:absolute",
      "left:0",
      "right:0",
      "bottom:0",
      "height:18px",
      "background:rgba(0,0,0,0.35)",
      "z-index:20",
    ].join(";");

    const { el, groups } = buildOverlay(markers, video.duration, video);
    overlayEl = el;
    bar.appendChild(overlayEl);

    player.appendChild(bar);
    wireVisibility(bar, groups);
  }

  async function placeSymbols(sceneId) {
    const video = findVideoEl();
    if (!video) {
      retryPlacement(sceneId, 1);
      return;
    }
    if (video.readyState < 1 || !video.duration || !isFinite(video.duration)) {
      video.addEventListener("loadedmetadata", () => placeSymbols(sceneId), { once: true });
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

    clearOverlay();
    const scrubber = findScrubber();
    if (scrubber) {
      renderOnScrubber(scrubber, video, markers);
    } else {
      renderFallbackBar(video, markers);
    }
  }

  function retryPlacement(sceneId, attempt) {
    if (attempt > MAX_PLACEMENT_RETRIES) return;
    placementTimer = setTimeout(() => {
      if (currentSceneId() !== sceneId) return;
      placeSymbols(sceneId);
    }, PLACEMENT_RETRY_MS);
  }

  function refreshForCurrentPage() {
    clearOverlay();
    const sceneId = currentSceneId();
    if (!sceneId) return;
    placeSymbols(sceneId);
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
