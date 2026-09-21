// Marker Improvements — UI addon
//
// Overlays each scene marker's tag image on the video scrubber (seek bar)
// at that marker's timestamp — hidden until you hover the scrubber, so it
// doesn't clutter the player otherwise. Click an icon to jump straight to
// that marker.
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
//   Uses each marker's primary tag's own image (Settings on a tag page
//   lets you upload one). A marker whose tag has no image gets a small
//   default pin instead.

(function () {
  "use strict";

  const DEFAULT_ICON = "📍";
  const ICON_SIZE_PX = 22;

  const SCRUBBER_SELECTORS = [
    ".vjs-progress-control .vjs-progress-holder",
    ".vjs-progress-control",
    ".video-js .vjs-progress-holder",
    ".vjs-control-bar .vjs-progress-holder",
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
            primary_tag { name image_path }
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
  let hoverTarget = null;
  let showHandler = null;
  let hideHandler = null;
  let placementTimer = null;

  function clearOverlay() {
    if (overlayEl) {
      overlayEl.remove();
      overlayEl = null;
    }
    if (hoverTarget && showHandler && hideHandler) {
      hoverTarget.removeEventListener("mouseenter", showHandler);
      hoverTarget.removeEventListener("mouseleave", hideHandler);
    }
    hoverTarget = null;
    showHandler = null;
    hideHandler = null;
    if (placementTimer) {
      clearTimeout(placementTimer);
      placementTimer = null;
    }
  }

  function makeIcon(marker, duration, video) {
    const pct = Math.min(100, Math.max(0, (marker.seconds / duration) * 100));
    const tagName = (marker.primary_tag && marker.primary_tag.name) || "";
    const imagePath = marker.primary_tag && marker.primary_tag.image_path;
    const label = `${formatTime(marker.seconds)} — ${marker.title || tagName || "marker"}`;

    const basePos = [
      "position:absolute",
      `left:${pct}%`,
      "top:50%",
      "transform:translate(-50%,-50%)",
      "pointer-events:inherit", // cascades from the overlay's own hover-toggled value
      "cursor:pointer",
      "user-select:none",
    ];

    let el;
    if (imagePath) {
      el = document.createElement("img");
      el.src = imagePath;
      el.alt = tagName || "marker";
      el.style.cssText = basePos.concat([
        `width:${ICON_SIZE_PX}px`,
        `height:${ICON_SIZE_PX}px`,
        "object-fit:cover",
        "border-radius:4px",
        "border:1px solid rgba(255,255,255,0.85)",
        "box-shadow:0 0 4px rgba(0,0,0,0.85)",
      ]).join(";");
      // If the tag image fails to load, fall back to the default pin
      // instead of showing a broken-image icon.
      el.addEventListener("error", () => {
        const fallback = document.createElement("span");
        fallback.textContent = DEFAULT_ICON;
        fallback.title = label;
        fallback.style.cssText = basePos.concat(["font-size:16px", "text-shadow:0 0 2px #000, 0 0 3px #000"]).join(";");
        fallback.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          video.currentTime = marker.seconds;
        });
        el.replaceWith(fallback);
      });
    } else {
      el = document.createElement("span");
      el.textContent = DEFAULT_ICON;
      el.style.cssText = basePos.concat(["font-size:16px", "text-shadow:0 0 2px #000, 0 0 3px #000"]).join(";");
    }

    el.title = label;
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      video.currentTime = marker.seconds;
    });
    return el;
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
    markers.forEach((m) => el.appendChild(makeIcon(m, duration, video)));
    return el;
  }

  function wireHover(container, overlay) {
    hoverTarget = container;
    showHandler = () => {
      overlay.style.opacity = "1";
      overlay.style.pointerEvents = "auto";
    };
    hideHandler = () => {
      overlay.style.opacity = "0";
      overlay.style.pointerEvents = "none";
    };
    container.addEventListener("mouseenter", showHandler);
    container.addEventListener("mouseleave", hideHandler);
  }

  function renderOnScrubber(scrubber, video, markers) {
    const computed = getComputedStyle(scrubber);
    if (computed.position === "static") {
      scrubber.style.position = "relative";
    }
    overlayEl = buildOverlay(markers, video.duration, video);
    scrubber.appendChild(overlayEl);
    wireHover(scrubber, overlayEl);
  }

  function renderFallbackBar(video, markers) {
    // Guaranteed-to-work fallback: a thin bar directly under the video,
    // used only if none of SCRUBBER_SELECTORS matched.
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
    wireHover(bar, overlayEl);
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
