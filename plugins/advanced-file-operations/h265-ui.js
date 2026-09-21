// Advanced File Operations — UI addon
//
// Adds two buttons on individual scene pages:
//   - "Convert to H265"   — re-encode just this scene's file
//   - "Split at Markers"  — cut the file at every marker into separate
//                            scenes, carrying markers/title/performers/
//                            tags/studio into each new part
// instead of only being able to run these from Settings > Tasks against
// the whole library.
//
// How it finds/places the buttons:
//   Stash's internal component names occasionally change between
//   versions, so rather than depending on one exact React component to
//   patch (which could silently stop working after a Stash upgrade), this
//   script:
//     1. Watches the page with PluginApi.Event (falls back to a plain
//        MutationObserver on older Stash versions that don't have
//        PluginApi.Event yet).
//     2. Tries to slot the buttons into Stash's own scene toolbar by
//        looking for a couple of known container selectors.
//     3. If it can't find one, it falls back to small fixed-position
//        buttons in the corner of the page — so the feature still works
//        even if step 2's selectors are stale for your version.
//   If you want them properly merged into your toolbar and the fallback
//   buttons are showing instead, open devtools on a scene page, find the
//   element that wraps Stash's own toolbar buttons, and add its selector
//   to TOOLBAR_SELECTORS below.

(function () {
  "use strict";

  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "advancedFileOperations";

  const TOOLBAR_SELECTORS = [
    ".scene-toolbar-group",
    ".scene-toolbar .btn-toolbar",
    ".scene-header .operations",
  ];

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

  // Tries the modern args_map form first (Stash v0.25+), falls back to the
  // older PluginArgInput list form for older servers.
  async function runTask(description, argsMap) {
    const modern = `
      mutation($plugin_id: ID!, $description: String, $args_map: Map) {
        runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map)
      }`;
    const legacy = `
      mutation($plugin_id: ID!, $description: String, $args: [PluginArgInput!]) {
        runPluginTask(plugin_id: $plugin_id, description: $description, args: $args)
      }`;

    try {
      await callGQL(modern, { plugin_id: PLUGIN_ID, description, args_map: argsMap });
    } catch (err) {
      console.warn("[H265 Transcoder] args_map form failed, trying legacy args form:", err);
      const args = Object.entries(argsMap).map(([key, value]) => ({ key, value: { str: String(value) } }));
      await callGQL(legacy, { plugin_id: PLUGIN_ID, description, args });
    }
  }

  function runConvertScene(sceneId) {
    return runTask(`Convert scene ${sceneId} to H265`, {
      mode: "convert_scene",
      scene_id: String(sceneId),
    });
  }

  function runRepairScene(sceneId) {
    return runTask(`Repair scene ${sceneId}`, {
      mode: "repair_scene",
      scene_id: String(sceneId),
      keep_original: "true",
    });
  }

  function runSplitScene(sceneId, opts) {
    const argsMap = {
      mode: "split_scene",
      scene_id: String(sceneId),
      keep_original: opts.keepOriginal ? "true" : "false",
      accurate: opts.accurate ? "true" : "false",
    };
    if (opts.cutSeconds && opts.cutSeconds.length) {
      argsMap.cut_seconds = opts.cutSeconds.join(",");
    }
    return runTask(`Split scene ${sceneId} at markers`, argsMap);
  }

  async function fetchMarkers(sceneId) {
    const query = `
      query($id: ID!) {
        findScene(id: $id) {
          scene_markers { id seconds title primary_tag { name } }
        }
      }`;
    const data = await callGQL(query, { id: sceneId });
    return (data.findScene.scene_markers || [])
      .slice()
      .sort((a, b) => a.seconds - b.seconds);
  }

  function formatTime(seconds) {
    const s = Math.floor(seconds % 60).toString().padStart(2, "0");
    const m = Math.floor(seconds / 60);
    return `${m}:${s}`;
  }

  // Shows a checklist of the scene's markers so the person can pick exactly
  // which ones to cut at, instead of always splitting at every marker.
  // Resolves to { cutSeconds, keepOriginal, accurate }, or null if cancelled.
  function openSplitDialog(markers) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.id = "h265-split-dialog-overlay";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:3000;" +
        "display:flex;align-items:center;justify-content:center;font-family:sans-serif;";

      const box = document.createElement("div");
      box.style.cssText =
        "background:#242730;color:#eee;padding:20px 24px;border-radius:8px;" +
        "max-width:440px;width:90%;max-height:80vh;overflow:auto;box-shadow:0 4px 24px rgba(0,0,0,0.5);";

      const heading = document.createElement("h5");
      heading.style.marginTop = "0";
      heading.textContent = "Split scene — choose where to cut";
      box.appendChild(heading);

      const hint = document.createElement("p");
      hint.style.cssText = "font-size:0.85em;opacity:0.75;margin-bottom:14px;";
      hint.textContent =
        "Check the markers you want to cut at. Markers you leave unchecked " +
        "aren't cut points, but they're still carried into whichever part " +
        "they end up in.";
      box.appendChild(hint);

      const cuttable = markers.filter((m) => m.seconds > 0);
      const checkboxes = [];

      if (cuttable.length === 0) {
        const none = document.createElement("p");
        none.textContent = "This scene has no markers after 0:00 to cut at.";
        box.appendChild(none);
      } else {
        const list = document.createElement("div");
        list.style.cssText = "display:flex;flex-direction:column;gap:6px;margin-bottom:16px;";
        cuttable.forEach((m) => {
          const label = document.createElement("label");
          label.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer;";
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = true;
          cb.dataset.seconds = String(m.seconds);
          const text = document.createElement("span");
          const name = m.title || (m.primary_tag && m.primary_tag.name) || "marker";
          text.textContent = `${formatTime(m.seconds)} — ${name}`;
          label.appendChild(cb);
          label.appendChild(text);
          list.appendChild(label);
          checkboxes.push(cb);
        });
        box.appendChild(list);
      }

      const optionsWrap = document.createElement("div");
      optionsWrap.style.cssText = "display:flex;flex-direction:column;gap:6px;margin-bottom:18px;font-size:0.9em;";

      const keepLabel = document.createElement("label");
      keepLabel.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer;";
      const keepCb = document.createElement("input");
      keepCb.type = "checkbox";
      keepCb.checked = true;
      keepLabel.appendChild(keepCb);
      keepLabel.appendChild(document.createTextNode("Keep original file"));
      optionsWrap.appendChild(keepLabel);

      const accLabel = document.createElement("label");
      accLabel.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer;";
      const accCb = document.createElement("input");
      accCb.type = "checkbox";
      accCb.checked = false;
      accLabel.appendChild(accCb);
      accLabel.appendChild(document.createTextNode("Frame-accurate cuts (slower, re-encodes)"));
      optionsWrap.appendChild(accLabel);

      box.appendChild(optionsWrap);

      const btnRow = document.createElement("div");
      btnRow.style.cssText = "display:flex;justify-content:flex-end;gap:8px;";

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn-secondary";
      cancelBtn.textContent = "Cancel";
      cancelBtn.addEventListener("click", () => {
        overlay.remove();
        resolve(null);
      });

      const confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = "btn btn-primary";
      confirmBtn.textContent = "Split";
      confirmBtn.disabled = cuttable.length === 0;
      confirmBtn.addEventListener("click", () => {
        const cutSeconds = checkboxes.filter((cb) => cb.checked).map((cb) => cb.dataset.seconds);
        if (cutSeconds.length === 0) {
          window.alert("Check at least one marker to cut at.");
          return;
        }
        overlay.remove();
        resolve({ cutSeconds, keepOriginal: keepCb.checked, accurate: accCb.checked });
      });

      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(confirmBtn);
      box.appendChild(btnRow);

      overlay.appendChild(box);
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) {
          overlay.remove();
          resolve(null);
        }
      });
      document.body.appendChild(overlay);
    });
  }

  function currentSceneId() {
    const match = window.location.pathname.match(/\/scenes\/(\d+)/);
    return match ? match[1] : null;
  }

  function makeButton({ id, label, title, className, onClick }) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.id = id;
    btn.className = className || "btn btn-secondary";
    btn.title = title;
    btn.textContent = label;

    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = "Working…";
      try {
        const result = await onClick();
        if (result && result.cancelled) {
          btn.textContent = originalText;
          btn.disabled = false;
          return;
        }
        btn.textContent = "Queued ✓";
        setTimeout(() => {
          btn.textContent = originalText;
          btn.disabled = false;
        }, 4000);
      } catch (err) {
        console.error(`[H265 Transcoder] ${id} failed:`, err);
        btn.textContent = "Failed — see console";
        btn.classList.add("btn-danger");
        setTimeout(() => {
          btn.textContent = originalText;
          btn.classList.remove("btn-danger");
          btn.disabled = false;
        }, 4000);
      }
    });

    return btn;
  }

  function removeAnyExistingButtons() {
    ["h265-convert-btn", "h265-split-btn", "h265-repair-btn"].forEach((id) => {
      const existing = document.getElementById(id);
      if (existing) existing.remove();
    });
  }

  function placeButtons() {
    const sceneId = currentSceneId();
    removeAnyExistingButtons();
    if (!sceneId) return;

    const convertBtn = makeButton({
      id: "h265-convert-btn",
      label: "Convert to H265",
      title: "Re-encode this scene's video to H.265 (visually lossless)",
      onClick: () => runConvertScene(sceneId),
    });

    const splitBtn = makeButton({
      id: "h265-split-btn",
      label: "Split at Markers…",
      title: "Cut this scene into a new scene per chosen marker, carrying markers, title, performers, tags and studio into each part",
      onClick: async () => {
        const markers = await fetchMarkers(sceneId);
        const choice = await openSplitDialog(markers);
        if (!choice) {
          return { cancelled: true };
        }
        return runSplitScene(sceneId, choice);
      },
    });

    const repairBtn = makeButton({
      id: "h265-repair-btn",
      label: "Repair File",
      title: "Check this scene's file for corruption and repair it (lossless remux first, tolerant re-encode as a fallback). Safe to click on a healthy file — it'll just report nothing to do.",
      onClick: () => runRepairScene(sceneId),
    });

    for (const selector of TOOLBAR_SELECTORS) {
      const container = document.querySelector(selector);
      if (container) {
        container.appendChild(convertBtn);
        container.appendChild(splitBtn);
        container.appendChild(repairBtn);
        return;
      }
    }

    // Fallback: small floating buttons, guaranteed to work regardless of
    // Stash's internal toolbar markup for this version.
    const wrap = document.createElement("div");
    wrap.id = "h265-floating-wrap";
    wrap.style.position = "fixed";
    wrap.style.bottom = "16px";
    wrap.style.right = "16px";
    wrap.style.zIndex = "2000";
    wrap.style.display = "flex";
    wrap.style.gap = "8px";
    convertBtn.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
    splitBtn.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
    repairBtn.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
    wrap.appendChild(convertBtn);
    wrap.appendChild(splitBtn);
    wrap.appendChild(repairBtn);
    document.body.appendChild(wrap);
  }

  function removeAnyExistingButtonsIncludingWrap() {
    removeAnyExistingButtons();
    const wrap = document.getElementById("h265-floating-wrap");
    if (wrap) wrap.remove();
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  }

  const schedulePlaceButtons = debounce(() => {
    removeAnyExistingButtonsIncludingWrap();
    placeButtons();
  }, 300);

  if (window.PluginApi && window.PluginApi.Event && typeof window.PluginApi.Event.addEventListener === "function") {
    // Preferred: official navigation event (Stash v0.25+).
    window.PluginApi.Event.addEventListener("stash:location", schedulePlaceButtons);
    schedulePlaceButtons();
  } else {
    // Fallback for older Stash versions: watch the DOM for route changes,
    // since there's no SPA-navigation hook available.
    schedulePlaceButtons();
    const observer = new MutationObserver(schedulePlaceButtons);
    observer.observe(document.body, { childList: true, subtree: true });
  }
})();
