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
//   correctly, still hover-to-reveal — just not layered pixel-for-pixel
//   on Stash's own control bar).
//   If you want it precisely on your real scrubber and the fallback bar
//   is showing instead, open devtools on a scene page, find the element
//   that is the actual seek/progress bar, and add its selector to
//   SCRUBBER_SELECTORS.
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
  let resizeObserver = null;
  let windowResizeHandler = null;
  // {target, type, handler} for every listener wireVisibility() registered
  // (some on `document`, not just the scrubber), so clearOverlay() can
  // undo all of them without needing a fixed set of named variables.
  let visibilityListeners = [];

  function clearOverlay() {
    if (overlayEl) {
      overlayEl.remove();
      overlayEl = null;
    }
    visibilityListeners.forEach(({ target, type, handler }) => target.removeEventListener(type, handler));
    visibilityListeners = [];
    if (placementTimer) {
      clearTimeout(placementTimer);
      placementTimer = null;
    }
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    if (windowResizeHandler) {
      window.removeEventListener("resize", windowResizeHandler);
      windowResizeHandler = null;
    }
  }

  // A marker's primary tag plus its other tags, deduped, filtered down to
  // just the ones that actually have an image uploaded — these are what
  // get shown for that marker (see makeMarkerIcons below).
  function tagsWithImages(marker) {
    const seen = new Set();
    const result = [];
    const consider = (tag) => {
      if (!tag || !tag.image_path) return;
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
  // marker just gets no icon, rather than a generic placeholder.
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
      "pointer-events:inherit", // cascades from the overlay's own hover-toggled value
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

  function buildOverlay(markers, duration, video) {
    const el = document.createElement("div");
    el.id = "marker-symbols-overlay";
    el.style.cssText = [
      "position:absolute",
      "left:0",
      "top:0",
      "width:100%",
      "height:100%",
      "z-index:20",
      "opacity:0",
      "pointer-events:none",
      "transition:opacity 0.15s ease",
    ].join(";");
    markers.forEach((m) => {
      const icons = makeMarkerIcons(m, duration, video);
      if (icons) el.appendChild(icons);
    });
    return el;
  }

  // Shows `overlay` on hover, but also while the scrubber is actively
  // being used: mouse/touch held down for a seek-drag (which can continue
  // after the pointer leaves the bar itself — mouseup/touchend are
  // watched on the whole document so it doesn't get stuck visible), or
  // keyboard-focused. Touch devices have no hover at all, so without the
  // touch handling here the icons would never show up on them.
  function wireVisibility(container, overlay) {
    let hovering = false;
    let active = false;

    const sync = () => {
      const visible = hovering || active;
      overlay.style.opacity = visible ? "1" : "0";
      overlay.style.pointerEvents = visible ? "auto" : "none";
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

  // Positions `overlay` (parented to `player`, not `scrubber`) so it sits
  // exactly over `scrubber`'s own bounding box, but tall enough to fit a
  // full-size icon regardless of how thin the real scrubber track is.
  function positionOverlayOverScrubber(scrubber, player, overlay) {
    const scrubberRect = scrubber.getBoundingClientRect();
    const playerRect = player.getBoundingClientRect();
    const height = Math.max(scrubberRect.height, ICON_SIZE_PX + 6);
    overlay.style.left = `${scrubberRect.left - playerRect.left}px`;
    overlay.style.top = `${scrubberRect.top - playerRect.top + scrubberRect.height / 2 - height / 2}px`;
    overlay.style.width = `${scrubberRect.width}px`;
    overlay.style.height = `${height}px`;
  }

  function renderOnScrubber(scrubber, video, markers) {
    // Most players' real scrubber/progress track is only a few px tall,
    // and some themes clip it (overflow:hidden) for a rounded-track look.
    // A 22px icon appended as a *child* of that track would get silently
    // cut down to an invisible sliver — so instead the overlay is parented
    // to the roomier player container and explicitly sized/positioned to
    // sit exactly over the scrubber's own bounding box, kept in sync on
    // resize. Icons are still positioned left:pct% within that overlay,
    // so they still line up with the scrubber exactly.
    const player = scrubber.closest(".video-js, .vjs-container") || scrubber.parentElement;
    if (!player) {
      renderFallbackBar(video, markers);
      return;
    }

    const computed = getComputedStyle(player);
    if (computed.position === "static") {
      player.style.position = "relative";
    }

    overlayEl = buildOverlay(markers, video.duration, video);
    player.appendChild(overlayEl);

    const reposition = () => positionOverlayOverScrubber(scrubber, player, overlayEl);
    reposition();

    if (window.ResizeObserver) {
      resizeObserver = new ResizeObserver(reposition);
      resizeObserver.observe(scrubber);
      resizeObserver.observe(player);
    } else {
      windowResizeHandler = reposition;
      window.addEventListener("resize", windowResizeHandler);
    }

    wireVisibility(scrubber, overlayEl);
    console.info("[Marker Symbols] Rendering on the real scrubber:", scrubber);
  }

  function renderFallbackBar(video, markers) {
    // Guaranteed-to-work fallback: a thin bar directly under the video,
    // used only if none of SCRUBBER_SELECTORS matched.
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

    overlayEl = buildOverlay(markers, video.duration, video);
    overlayEl.style.cssText = "position:absolute;inset:0;opacity:0;pointer-events:none;transition:opacity 0.15s ease;";
    bar.appendChild(overlayEl);

    player.appendChild(bar);
    wireVisibility(bar, overlayEl);
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
