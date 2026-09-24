// Advanced File Operations — UI addon
//
// Adds a single "File Operations" dropdown (scissors icon) on individual
// scene pages, with three actions:
//   - "Convert to H265…"  — opens a small dialog to pick a quality preset
//                            (or a custom CRF), then re-encodes just this
//                            scene's file. Greyed out once the file's
//                            already H265. With "keep original" checked
//                            (the default), the source file is never
//                            deleted — the new file is attached to the
//                            same scene and set as its primary file, and
//                            the original stays on the scene as a
//                            secondary file.
//   - "Split at Markers…" — cut the file at every marker into separate
//                            scenes, carrying markers/title/performers/
//                            tags/studio into each new part
//   - "Repair File"        — check the file for decode errors and fix it
// instead of only being able to run these from Settings > Tasks against
// the whole library.
//
// How it finds/places the dropdown:
//   Stash's internal component names occasionally change between
//   versions, so rather than depending on one exact React component to
//   patch (which could silently stop working after a Stash upgrade), this
//   script:
//     1. Watches the page with PluginApi.Event (falls back to a plain
//        MutationObserver on older Stash versions that don't have
//        PluginApi.Event yet).
//     2. Tries to slot the dropdown into Stash's own scene toolbar by
//        looking for a couple of known container selectors.
//     3. If it can't find one, it falls back to a small fixed-position
//        button in the corner of the page — so the feature still works
//        even if step 2's selectors are stale for your version.
//   If you want it properly merged into your toolbar and the fallback
//   button is showing instead, open devtools on a scene page, find the
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

  function runConvertScene(sceneId, opts) {
    opts = opts || {};
    const argsMap = {
      mode: "convert_scene",
      scene_id: String(sceneId),
      keep_original: opts.keepOriginal ? "true" : "false",
    };
    // A custom numeric CRF wins if given; otherwise send the named preset
    // (see QUALITY_PRESETS in h265_transcode.py — keep these in sync).
    if (opts.quality === "custom" && opts.crf != null) {
      argsMap.crf = String(opts.crf);
    } else {
      argsMap.quality = opts.quality || "visually_lossless";
    }
    return runTask(`Convert scene ${sceneId} to H265`, argsMap);
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
    if (opts.ranges && opts.ranges.length) {
      argsMap.ranges = opts.ranges.join(",");
    } else if (opts.cutSeconds && opts.cutSeconds.length) {
      argsMap.cut_seconds = opts.cutSeconds.join(",");
    }
    return runTask(`Split scene ${sceneId} at markers`, argsMap);
  }

  // Asks for each marker's end_seconds too (Stash v0.27+). Older versions
  // don't have that field and reject the whole query, so fall back to one
  // without it — markers then just have no end of their own.
  async function fetchMarkers(sceneId) {
    const query = (fields) => `
      query($id: ID!) {
        findScene(id: $id) {
          scene_markers { ${fields} }
        }
      }`;
    let data;
    try {
      data = await callGQL(query("id seconds end_seconds title primary_tag { name }"), { id: sceneId });
    } catch (err) {
      data = await callGQL(query("id seconds title primary_tag { name }"), { id: sceneId });
    }
    return (data.findScene.scene_markers || [])
      .slice()
      .sort((a, b) => a.seconds - b.seconds);
  }

  // Where a marker's clip ends in "whole marker" mode: its own end time if
  // it has one, else the next marker's start. null means "to the end of
  // the video" — the backend fills that in from the file's duration.
  function markerRangeEnd(marker, allMarkers) {
    if (marker.end_seconds != null && marker.end_seconds > marker.seconds) {
      return { end: marker.end_seconds, inferred: false };
    }
    const next = allMarkers.find((m) => m.seconds > marker.seconds);
    return { end: next ? next.seconds : null, inferred: true };
  }

  function formatTime(seconds) {
    const s = Math.floor(seconds % 60).toString().padStart(2, "0");
    const m = Math.floor(seconds / 60);
    return `${m}:${s}`;
  }

  // Shows a checklist of the scene's markers in one of two modes:
  //   - "whole" (default): each checked marker becomes its own clip, from
  //     its start to its end (see markerRangeEnd).
  //   - "points": the file is cut at each checked marker, so the parts
  //     together cover the whole video.
  // Resolves to { ranges | cutSeconds, keepOriginal, accurate }, or null if
  // cancelled.
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

      let mode = "whole";
      const modeWrap = document.createElement("div");
      modeWrap.style.cssText = "display:flex;flex-direction:column;gap:4px;margin-bottom:12px;font-size:0.9em;";
      [
        { value: "whole", text: "Each marker as its own clip (start → end)" },
        { value: "points", text: "Cut the video at each marker" },
      ].forEach((opt) => {
        const label = document.createElement("label");
        label.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer;";
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "h265-split-mode";
        radio.value = opt.value;
        radio.checked = opt.value === mode;
        radio.addEventListener("change", () => {
          mode = opt.value;
          renderList();
        });
        label.appendChild(radio);
        label.appendChild(document.createTextNode(opt.text));
        modeWrap.appendChild(label);
      });
      box.appendChild(modeWrap);

      const hint = document.createElement("p");
      hint.style.cssText = "font-size:0.85em;opacity:0.75;margin-bottom:14px;";
      box.appendChild(hint);

      const list = document.createElement("div");
      list.style.cssText = "display:flex;flex-direction:column;gap:6px;margin-bottom:16px;";
      box.appendChild(list);

      let checkboxes = [];

      // Rebuilds the checklist for the current mode. "points" can't cut at
      // 0:00, so it leaves those markers out; "whole" lists every marker
      // with the range it would be cut to.
      function renderList() {
        hint.textContent = mode === "whole"
          ? "Each checked marker becomes its own new scene, from where it starts " +
            "to where it ends (or to the next marker, if it has no end set). " +
            "Parts of the video outside every checked marker aren't in any new file."
          : "Check the markers you want to cut at. Markers you leave unchecked " +
            "aren't cut points, but they're still carried into whichever part " +
            "they end up in.";

        list.textContent = "";
        checkboxes = [];
        const shown = mode === "whole" ? markers : markers.filter((m) => m.seconds > 0);

        if (shown.length === 0) {
          const none = document.createElement("p");
          none.textContent = mode === "whole"
            ? "This scene has no markers."
            : "This scene has no markers after 0:00 to cut at.";
          list.appendChild(none);
        }

        shown.forEach((m) => {
          const label = document.createElement("label");
          label.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer;";
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = true;
          cb.dataset.seconds = String(m.seconds);
          const text = document.createElement("span");
          const name = m.title || (m.primary_tag && m.primary_tag.name) || "marker";
          if (mode === "whole") {
            const { end, inferred } = markerRangeEnd(m, markers);
            cb.dataset.end = end == null ? "" : String(end);
            const endText = end == null ? "end" : formatTime(end);
            text.textContent = `${formatTime(m.seconds)} – ${endText}${inferred ? "*" : ""} — ${name}`;
            if (inferred) {
              text.title = end == null
                ? "No end time set — runs to the end of the video"
                : "No end time set — runs until the next marker";
            }
          } else {
            text.textContent = `${formatTime(m.seconds)} — ${name}`;
          }
          label.appendChild(cb);
          label.appendChild(text);
          list.appendChild(label);
          checkboxes.push(cb);
        });

        confirmBtn.disabled = shown.length === 0;
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
      confirmBtn.addEventListener("click", () => {
        const checked = checkboxes.filter((cb) => cb.checked);
        if (checked.length === 0) {
          window.alert("Check at least one marker.");
          return;
        }
        overlay.remove();
        const common = { keepOriginal: keepCb.checked, accurate: accCb.checked };
        if (mode === "whole") {
          // "start-end", with an empty end meaning "to the end of the video".
          resolve({ ...common, ranges: checked.map((cb) => `${cb.dataset.seconds}-${cb.dataset.end}`) });
        } else {
          resolve({ ...common, cutSeconds: checked.map((cb) => cb.dataset.seconds) });
        }
      });

      btnRow.appendChild(cancelBtn);
      btnRow.appendChild(confirmBtn);
      box.appendChild(btnRow);
      // Only now — renderList() touches confirmBtn.
      renderList();

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

  // Quality presets offered here — keep the `value`s in sync with
  // QUALITY_PRESETS in h265_transcode.py.
  const QUALITY_OPTIONS = [
    { value: "highest", label: "Highest quality (CRF 16) — largest files" },
    { value: "visually_lossless", label: "Visually lossless (CRF 18) — recommended" },
    { value: "balanced", label: "Balanced (CRF 20) — smaller, minimal visible difference" },
    { value: "smaller", label: "Smaller files (CRF 23)" },
    { value: "smallest", label: "Smallest files (CRF 28) — visibly softer" },
    { value: "custom", label: "Custom CRF…" },
  ];

  // Lets the person pick an encode quality (and whether to keep the
  // original file) before queuing a single-scene H265 conversion, instead
  // of always encoding at a hardcoded default.
  function openQualityDialog() {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.id = "h265-quality-dialog-overlay";
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:3000;" +
        "display:flex;align-items:center;justify-content:center;font-family:sans-serif;";

      const box = document.createElement("div");
      box.style.cssText =
        "background:#242730;color:#eee;padding:20px 24px;border-radius:8px;" +
        "max-width:420px;width:90%;max-height:80vh;overflow:auto;box-shadow:0 4px 24px rgba(0,0,0,0.5);";

      const heading = document.createElement("h5");
      heading.style.marginTop = "0";
      heading.textContent = "Convert to H265 — choose quality";
      box.appendChild(heading);

      const hint = document.createElement("p");
      hint.style.cssText = "font-size:0.85em;opacity:0.75;margin-bottom:14px;";
      hint.textContent =
        "Lower CRF = closer to source quality, bigger files. Higher CRF = " +
        "smaller files, softer picture.";
      box.appendChild(hint);

      const select = document.createElement("select");
      select.className = "form-control";
      select.style.cssText = "width:100%;margin-bottom:12px;";
      QUALITY_OPTIONS.forEach((opt) => {
        const option = document.createElement("option");
        option.value = opt.value;
        option.textContent = opt.label;
        select.appendChild(option);
      });
      select.value = "visually_lossless";
      box.appendChild(select);

      const customWrap = document.createElement("div");
      customWrap.style.cssText = "display:none;margin-bottom:12px;";
      const customLabel = document.createElement("label");
      customLabel.style.cssText = "display:block;font-size:0.85em;margin-bottom:4px;";
      customLabel.textContent = "CRF (0-51, lower = higher quality)";
      const customInput = document.createElement("input");
      customInput.type = "number";
      customInput.min = "0";
      customInput.max = "51";
      customInput.value = "18";
      customInput.className = "form-control";
      customWrap.appendChild(customLabel);
      customWrap.appendChild(customInput);
      box.appendChild(customWrap);

      select.addEventListener("change", () => {
        customWrap.style.display = select.value === "custom" ? "block" : "none";
      });

      const optionsWrap = document.createElement("div");
      optionsWrap.style.cssText = "margin-bottom:18px;font-size:0.9em;";
      const keepLabel = document.createElement("label");
      keepLabel.style.cssText = "display:flex;align-items:center;gap:8px;cursor:pointer;";
      const keepCb = document.createElement("input");
      keepCb.type = "checkbox";
      keepCb.checked = true;
      keepLabel.appendChild(keepCb);
      keepLabel.appendChild(document.createTextNode(
        "Keep original file (recommended — new file becomes the scene's " +
        "primary file, original stays attached as a secondary file)"
      ));
      optionsWrap.appendChild(keepLabel);
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
      confirmBtn.textContent = "Convert";
      confirmBtn.addEventListener("click", () => {
        const quality = select.value;
        let crf = null;
        if (quality === "custom") {
          crf = parseInt(customInput.value, 10);
          if (Number.isNaN(crf) || crf < 0 || crf > 51) {
            window.alert("Enter a CRF between 0 and 51.");
            return;
          }
        }
        overlay.remove();
        resolve({ quality, crf, keepOriginal: keepCb.checked });
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

  // Mirrors ALREADY_DONE_CODECS / DONE_TAG_NAME in h265_transcode.py —
  // keep in sync. Used purely to grey out "Convert to H265" client-side;
  // the task itself re-checks server-side regardless.
  const ALREADY_DONE_CODECS = new Set(["hevc", "h265", "x265"]);
  const DONE_TAG_NAME = "H265 Converted";

  async function fetchSceneCodecInfo(sceneId) {
    const query = `
      query($id: ID!) {
        findScene(id: $id) {
          files { video_codec }
          tags { name }
        }
      }`;
    const data = await callGQL(query, { id: sceneId });
    const scene = data.findScene || {};
    const files = scene.files || [];
    const codec = ((files[0] && files[0].video_codec) || "").toLowerCase();
    const tagNames = (scene.tags || []).map((t) => t.name);
    return { codec, tagNames, hasFile: files.length > 0 };
  }

  function isAlreadyH265({ codec, tagNames }) {
    return ALREADY_DONE_CODECS.has(codec) || tagNames.includes(DONE_TAG_NAME);
  }

  // Feather-style scissors icon, inlined so the plugin has no external
  // asset/CDN dependency. currentColor means it follows Stash's own
  // toolbar button text color in both light and dark themes.
  const SCISSORS_ICON_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
    'style="display:block;flex:none;">' +
    '<circle cx="6" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle>' +
    '<line x1="20" y1="4" x2="8.12" y2="15.88"></line>' +
    '<line x1="14.47" y1="14.48" x2="20" y2="20"></line>' +
    '<line x1="8.12" y1="8.12" x2="12" y2="12"></line></svg>';

  // One row inside the File Operations dropdown. Handles its own
  // working/success/failure feedback, same as the old standalone buttons
  // did, then hands control back to the caller via closeMenu.
  function makeMenuItem({ id, label, title, onClick, closeMenu }) {
    const item = document.createElement("button");
    item.type = "button";
    item.id = id;
    item.title = title;
    item.textContent = label;
    item.style.cssText =
      "display:block;width:100%;text-align:left;background:none;border:0;" +
      "padding:8px 16px;cursor:pointer;color:inherit;font-size:0.9em;white-space:nowrap;";
    item.addEventListener("mouseenter", () => {
      if (!item.disabled) item.style.background = "rgba(255,255,255,0.08)";
    });
    item.addEventListener("mouseleave", () => {
      item.style.background = "none";
    });

    item.addEventListener("click", async (e) => {
      e.stopPropagation();
      const originalText = item.textContent;
      item.disabled = true;
      item.textContent = "Working…";
      try {
        const result = await onClick();
        if (result && result.cancelled) {
          item.textContent = originalText;
          item.disabled = false;
          return;
        }
        item.textContent = "Queued ✓";
        setTimeout(() => {
          item.textContent = originalText;
          item.disabled = false;
          closeMenu();
        }, 1200);
      } catch (err) {
        console.error(`[Advanced File Operations] ${id} failed:`, err);
        item.textContent = "Failed — see console";
        item.style.color = "#e35d6a";
        setTimeout(() => {
          item.textContent = originalText;
          item.style.color = "";
          item.disabled = false;
        }, 4000);
      }
    });

    return item;
  }

  function removeAnyExistingButtons() {
    const existing = document.getElementById("h265-ops-wrap");
    if (existing) existing.remove();
  }

  function placeButtons() {
    const sceneId = currentSceneId();
    removeAnyExistingButtons();
    if (!sceneId) return;

    const wrap = document.createElement("div");
    wrap.id = "h265-ops-wrap";
    wrap.style.cssText = "position:relative;display:inline-block;";

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.id = "h265-ops-toggle";
    toggle.className = "btn btn-secondary";
    toggle.title = "File operations — convert to H265, split at markers, or repair this scene's file";
    toggle.setAttribute("aria-label", "File operations");
    toggle.style.cssText = "display:inline-flex;align-items:center;justify-content:center;padding-left:10px;padding-right:10px;";
    toggle.innerHTML = SCISSORS_ICON_SVG;

    const menu = document.createElement("div");
    menu.id = "h265-ops-menu";
    menu.style.cssText =
      "display:none;position:absolute;top:100%;left:0;margin-top:4px;" +
      "background:#242730;color:#eee;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.5);" +
      "min-width:230px;z-index:2500;overflow:hidden;padding:4px 0;";

    const closeMenu = () => {
      menu.style.display = "none";
    };
    const toggleMenu = () => {
      menu.style.display = menu.style.display === "none" ? "block" : "none";
    };

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleMenu();
    });

    const convertItem = makeMenuItem({
      id: "h265-convert-btn",
      label: "Convert to H265…",
      title: "Re-encode this scene's video to H.265, choosing a quality first",
      onClick: async () => {
        closeMenu();
        const choice = await openQualityDialog();
        if (!choice) {
          return { cancelled: true };
        }
        return runConvertScene(sceneId, choice);
      },
      closeMenu,
    });

    // Grey the item out once we know the scene's already H265 (or already
    // tagged converted) — best-effort, and only if no conversion is
    // currently in flight/just finished on this item (don't clobber that
    // state out from under the busy/success/failure feedback).
    fetchSceneCodecInfo(sceneId)
      .then((info) => {
        if (!info.hasFile || !isAlreadyH265(info) || convertItem.disabled) return;
        convertItem.disabled = true;
        convertItem.textContent = "Already H265";
        convertItem.title = "This scene's file is already H265/HEVC (or already tagged \"H265 Converted\") — nothing to convert.";
        convertItem.style.opacity = "0.5";
        convertItem.style.cursor = "not-allowed";
      })
      .catch((err) => {
        console.warn("[Advanced File Operations] Couldn't check current codec:", err);
      });

    const splitItem = makeMenuItem({
      id: "h265-split-btn",
      label: "Split at Markers…",
      title: "Cut this scene into a new scene per chosen marker, carrying markers, title, performers, tags and studio into each part",
      onClick: async () => {
        closeMenu();
        const markers = await fetchMarkers(sceneId);
        const choice = await openSplitDialog(markers);
        if (!choice) {
          return { cancelled: true };
        }
        return runSplitScene(sceneId, choice);
      },
      closeMenu,
    });

    const repairItem = makeMenuItem({
      id: "h265-repair-btn",
      label: "Repair File",
      title: "Check this scene's file for corruption and repair it (lossless remux first, tolerant re-encode as a fallback). Safe to click on a healthy file — it'll just report nothing to do.",
      onClick: () => runRepairScene(sceneId),
      closeMenu,
    });

    menu.appendChild(convertItem);
    menu.appendChild(splitItem);
    menu.appendChild(repairItem);
    wrap.appendChild(toggle);
    wrap.appendChild(menu);

    for (const selector of TOOLBAR_SELECTORS) {
      const container = document.querySelector(selector);
      if (container) {
        container.appendChild(wrap);
        return;
      }
    }

    // Fallback: a small floating button, guaranteed to work regardless of
    // Stash's internal toolbar markup for this version.
    wrap.style.position = "fixed";
    wrap.style.bottom = "16px";
    wrap.style.right = "16px";
    wrap.style.zIndex = "2000";
    toggle.style.boxShadow = "0 2px 8px rgba(0,0,0,0.4)";
    document.body.appendChild(wrap);
  }

  // Closes the dropdown on any click outside it. Registered once — the
  // wrap element is looked up fresh each time so this keeps working across
  // re-renders/navigation without piling up duplicate listeners.
  document.addEventListener("click", (e) => {
    const wrap = document.getElementById("h265-ops-wrap");
    const menu = document.getElementById("h265-ops-menu");
    if (wrap && menu && !wrap.contains(e.target)) {
      menu.style.display = "none";
    }
  });

  function debounce(fn, ms) {
    let t;
    return (...a) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...a), ms);
    };
  }

  const schedulePlaceButtons = debounce(() => {
    removeAnyExistingButtons();
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
