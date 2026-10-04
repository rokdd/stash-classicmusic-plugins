// Markers as Chapters — marker scrapers
//
// Stash scrapes scenes, galleries, performers … but not markers. This
// adds marker scrapers that work like Stash's own (see marker_scrapers.py):
// a "Scrape markers" button next to "Create Marker" in a scene's Markers
// tab lists every marker scraper — one entry per scraper that scrapes the
// scene itself, and one per scene URL a URL scraper handles (plus "Other
// URL…"), and one per scraper that reads text (pasted, or from a file),
// like Stash's scrape menu. The markers found are shown in a
// dialog to review: pick which to create, change titles and tags, shift
// all times (when the online video has a different intro), and markers
// already in the scene are flagged and not picked. Then "Create" adds
// them.
//
// Every marker needs a primary tag: the one the scraper names, or else the
// "Primary tag for scraped markers" setting (default "Chapter" — created
// if there's no such tag yet). Tag names match a tag's name or alias,
// upper/lower case ignored; tags that don't exist are left out.

(function () {
  "use strict";

  const PLUGIN_ID = "markersAsChapters";
  // Its settings used to be Marker Improvements' — still read from there.
  const OLD_PLUGIN_ID = "markerImprovements";
  const BUTTON_ID = "marker-scrapers-button";
  const MENU_ID = "marker-scrapers-menu";
  const DIALOG_ID = "marker-scrapers-dialog";
  const DEFAULT_PRIMARY = "Chapter";

  // The browser's own words for a lost connection ("Failed to fetch",
  // "NetworkError when attempting to fetch resource", "Load failed") and a
  // proxy's error page instead of an answer say little — said plainly.
  const LOST = "Lost the connection to the Stash server.";

  function gql(query, variables) {
    return fetch("/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    })
      .catch(() => { throw Object.assign(new Error(LOST), { lost: true }); })
      .then((r) => r.json().catch(() => {
        throw Object.assign(new Error(`${LOST} It answered “${r.status} ${r.statusText}” instead (a proxy's time limit?).`), { lost: true });
      }))
      .then((json) => {
        if (json.errors) throw new Error(json.errors.map((e) => e.message).join("; "));
        return json.data;
      });
  }

  async function runOperation(args) {
    const data = await gql(
      "mutation($plugin_id: ID!, $args: Map) { runPluginOperation(plugin_id: $plugin_id, args: $args) }",
      { plugin_id: PLUGIN_ID, args }
    );
    const result = data.runPluginOperation;
    if (result && typeof result === "object" && result.error) throw new Error(result.error);
    return result;
  }

  function sceneId() {
    const m = window.location.pathname.match(/\/scenes\/(\d+)/);
    return m ? m[1] : null;
  }

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (k === "style") Object.assign(node.style, v);
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (k in node) node[k] = v;
      else node.setAttribute(k, v);
    });
    children.flat().forEach((c) => c != null && node.append(c.nodeType ? c : String(c)));
    return node;
  }

  function formatTime(seconds) {
    if (seconds == null || isNaN(seconds)) return "";
    const s = Math.max(0, seconds);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = (s % 60).toFixed(s % 1 ? 1 : 0).padStart(s % 1 ? 4 : 2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  }

  // "1:02:03", "2:03", "123", "123.5" → seconds
  function parseTime(text) {
    const parts = String(text).trim().split(":").map(Number);
    if (!parts.length || parts.some((p) => isNaN(p))) return null;
    return parts.reduce((acc, p) => acc * 60 + p, 0);
  }

  // -- the button ---------------------------------------------------------------

  // The Markers tab's content: Stash's own .scene-markers-panel (its tab
  // panes have no ids in v0.31), else the active tab's pane when that tab
  // is labelled "Markers".
  function findMarkersPanel() {
    const own = document.querySelector(".scene-markers-panel");
    if (own) return own;
    const pane =
      document.querySelector('[id$="tabpane-scene-markers-panel"]') ||
      document.getElementById("scene-markers-panel");
    if (pane) return pane;
    const activeTab = document.querySelector(".nav-tabs .nav-link.active");
    return activeTab && /marker/i.test(activeTab.textContent) ? document.querySelector(".tab-pane.active") : null;
  }

  // Next to Stash's "Create Marker" button: the panel's primary button
  // outside any form and outside this plugin's marker list.
  function placeButton() {
    if (!sceneId()) return;
    const panel = findMarkersPanel();
    if (!panel || panel.querySelector(`#${BUTTON_ID}`)) return;
    const create = Array.from(panel.querySelectorAll("button.btn-primary")).find(
      (b) => !b.closest("form") && !b.closest("#marker-symbols-timeline")
    );
    if (!create) return;
    const button = el("button", {
      id: BUTTON_ID,
      type: "button",
      className: "btn btn-secondary ml-2",
      textContent: "Scrape markers…",
      onclick: (e) => openMenu(e.currentTarget),
    });
    create.insertAdjacentElement("afterend", button);
  }

  let placePending = false;
  new MutationObserver(() => {
    if (placePending) return;
    placePending = true;
    setTimeout(() => {
      placePending = false;
      placeButton();
    }, 200);
  }).observe(document.body, { childList: true, subtree: true });

  // -- the menu -------------------------------------------------------------------

  function closeMenu() {
    const menu = document.getElementById(MENU_ID);
    if (menu) menu.remove();
  }
  document.addEventListener("click", (e) => {
    const menu = document.getElementById(MENU_ID);
    if (menu && !menu.contains(e.target) && e.target.id !== BUTTON_ID) closeMenu();
  });

  // Which scrapers find nothing for a scene: checked in the background when
  // the menu opens (marker_available with "all": the files next to and in
  // the video, ARTE / ORF ON through the scene's URLs, OpenSubtitles' key),
  // and learnt from every scrape that came back empty. Those are turned off
  // in the menu, with the reason; "Check again" forgets it all.
  const menuChecks = new Map(); // "<scene>|<urls>" → Promise of {id: {count, why, label, setup}}
  const foundNothing = new Map(); // "<scene>|<scraper>|<url>" → why

  function nothingKey(scraperId, url) {
    return `${sceneId()}|${scraperId}|${url || ""}`;
  }

  function menuCheck(urls) {
    const key = `${sceneId()}|${urls.join(" ")}`;
    if (!menuChecks.has(key)) {
      menuChecks.set(key, runOperation({ mode: "marker_available", scene_id: sceneId(), all: true })
        .then((r) => (r && r.checked) || {})
        .catch(() => ({})));
    }
    return menuChecks.get(key);
  }

  // Turn a menu entry off (greyed, not clickable, the reason below it) or
  // add what was found to it.
  function markItem(button, state) {
    if (!button || !state) return;
    const note = button.querySelector(".mac-why") || el("div", { className: "mac-why small text-muted",
      style: { whiteSpace: "normal", maxWidth: "360px", fontSize: "0.8em" } });
    if (state.off) {
      button.disabled = true;
      button.classList.add("disabled");
      button.style.opacity = "0.55";
      button.title = state.why || "";
      note.textContent = `${state.setup ? "Not set up" : "Nothing for this scene"} — ${String(state.why || "nothing found").replace(/\s+/g, " ").slice(0, 160)}`;
    } else {
      note.textContent = state.label;
    }
    if (!note.isConnected) button.appendChild(note);
  }

  function urlMatches(scraper, url) {
    return (scraper.urls || []).some((p) => p && url.includes(p));
  }

  async function openMenu(button) {
    if (document.getElementById(MENU_ID)) return closeMenu();
    const menu = el("div", {
      id: MENU_ID,
      className: "dropdown-menu show",
      style: { position: "absolute", zIndex: 1050, maxHeight: "60vh", overflowY: "auto" },
    }, el("span", { className: "dropdown-item-text text-muted", textContent: "Loading scrapers…" }));
    const rect = button.getBoundingClientRect();
    menu.style.left = `${rect.left + window.scrollX}px`;
    menu.style.top = `${rect.bottom + window.scrollY + 2}px`;
    document.body.appendChild(menu);

    let scrapers;
    let urls = [];
    try {
      const [list, scene] = await Promise.all([
        runOperation({ mode: "marker_scrapers_list" }),
        gql("query($id: ID!) { findScene(id: $id) { urls } }", { id: sceneId() }),
      ]);
      scrapers = list || [];
      urls = (scene.findScene && scene.findScene.urls) || [];
    } catch (err) {
      menu.replaceChildren(el("span", { className: "dropdown-item-text text-danger", textContent: String(err.message || err) }));
      return;
    }
    const entries = []; // [button, scraper id, url, kind]
    const item = (label, run, scraperId, url, kind) => {
      const button = el("button", { type: "button", className: "dropdown-item", onclick: () => { closeMenu(); run(); } },
        el("span", { textContent: label }));
      if (scraperId) entries.push([button, scraperId, url || "", kind]);
      return button;
    };
    const items = [];
    // On top: what works on the scene itself (its file) and on text. A
    // scraper for websites goes below the line only — scraping "the scene"
    // with it just means scraping the scene's URL, listed there.
    const byUrl = scrapers.filter((s) => (s.urls || []).length);
    scrapers.filter((s) => s.fragment && (!(s.urls || []).length || s.fragment_in_menu))
      .forEach((s) => items.push(item(s.name, () => scrape(s, null), s.id, "", "scene")));
    scrapers.filter((s) => s.text).forEach((s) => items.push(item(`${s.name} — ${s.text_label || "paste text or pick a file…"}`, () => textDialog(s), s.id, "", "text")));
    items.push(item("Copy the scene's markers as text…", () => copySceneMarkers()));
    items.push(item("Composers from the titles…", () => composersDialog()));
    items.push(item("New composer…", () => newComposerDialog()));
    items.push(item("Markers and the scene's files…", () => filesDialog()));
    if (byUrl.length) {
      // A URL a scraper for that very site handles isn't offered to the
      // catch-all ones (a pattern like "http") too.
      const generic = (p) => /^https?:?\/*$/i.test(p);
      const specific = (s, u) => (s.urls || []).some((p) => p && !generic(p) && u.includes(p));
      const handledSpecifically = (u) => byUrl.some((s) => specific(s, u));
      if (items.length) items.push(el("div", { className: "dropdown-divider" }));
      byUrl.forEach((s) => {
        urls.filter((u) => specific(s, u) || (urlMatches(s, u) && !handledSpecifically(u))).forEach((u) => {
          let host = u;
          try { host = new URL(u).host.replace(/^www\./, ""); } catch (e) { /* keep it whole */ }
          items.push(item(`${s.name} — ${host}`, () => scrape(s, u), s.id, u, "url"));
        });
        items.push(item(`${s.name} — other URL…`, () => {
          const u = window.prompt(`URL to scrape markers from with ${s.name}:`);
          if (u && u.trim()) scrape(s, u.trim());
        }));
      });
    }
    if (!items.length) {
      items.push(el("span", { className: "dropdown-item-text text-muted", textContent: "No marker scrapers found." }));
    }
    const checking = el("span", { className: "dropdown-item-text small text-muted", textContent: "Checking what this scene has…" });
    const again = el("button", { type: "button", className: "dropdown-item small text-muted", textContent: "↻ Check again",
      onclick: (e) => {
        e.stopPropagation();
        [...menuChecks.keys()].filter((k) => k.startsWith(`${sceneId()}|`)).forEach((k) => menuChecks.delete(k));
        [...foundNothing.keys()].filter((k) => k.startsWith(`${sceneId()}|`)).forEach((k) => foundNothing.delete(k));
        closeMenu();
        openMenu(button);
      } });
    menu.replaceChildren(...items, el("div", { className: "dropdown-divider" }), checking);
    const apply = (checked) => {
      entries.forEach(([b, id, u, kind]) => {
        const learnt = foundNothing.get(nothingKey(id, u));
        const c = checked[id];
        if (learnt !== undefined) markItem(b, { off: true, why: learnt });
        else if (c && kind === "scene" && c.count === 0) markItem(b, { off: true, why: c.why });
        else if (c && c.setup) markItem(b, { off: true, setup: true, why: c.why }); // OpenSubtitles without a key: by words neither
        else if (c && kind === "scene" && (c.count || c.label)) markItem(b, { label: c.label || `${c.count} marker${c.count === 1 ? "" : "s"} found` });
      });
    };
    apply({}); // what earlier scrapes found out, at once
    apply(await menuCheck(urls));
    if (checking.isConnected) checking.replaceWith(again);
  }

  // -- scraping and the review dialog --------------------------------------------------

  // A text file's content in the right encoding: UTF-16 with a byte order
  // mark, else UTF-8 — and when that isn't valid, Windows-1252 (old
  // tracklists and CUE sheets often are: "schönen" as one byte).
  function decodeText(bytes) {
    if (bytes[0] === 0xff && bytes[1] === 0xfe) return new TextDecoder("utf-16le").decode(bytes);
    if (bytes[0] === 0xfe && bytes[1] === 0xff) return new TextDecoder("utf-16be").decode(bytes);
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch (e) {
      return new TextDecoder("windows-1252").decode(bytes);
    }
  }

  // What can be pasted — shown in the Plain text dialog, with the details
  // in the README on GitHub.
  const README_FORMATS = "https://github.com/rokdd/stash-classicmusic-plugins/tree/main/plugins/markers-as-chapters#what-you-can-paste";

  function readmeLink(text) {
    return el("a", { href: README_FORMATS, target: "_blank", rel: "noopener noreferrer", textContent: text || "More in the README ↗" });
  }

  function formatsHelp() {
    const example = (label, sample, note) => el("li", { className: "mb-1" },
      el("strong", { textContent: label }), note ? ` — ${note}` : "",
      el("pre", { className: "mb-0 mt-1 p-1", textContent: sample,
        style: { fontSize: "0.8em", background: "rgba(0,0,0,.25)", borderRadius: "3px", whiteSpace: "pre-wrap" } }));
    return el("div", { className: "small mb-2" },
      el("p", { className: "text-muted mb-1", textContent:
        "Pick a file or paste the text, check and edit it, then scrape. The dialog then says how the text was read." }),
      el("details", {},
        el("summary", { textContent: "Which formats can I paste?", style: { cursor: "pointer" } }),
        el("ul", { className: "mt-2 mb-1 pl-3" },
          example("Times and titles", "0:00 I. Allegro con brio\n7:41 - 17:30 II. Andante con moto\n[1:02:03] Finale",
            "one marker per line; a range gives the end too"),
          example("Titles only", "I. Allegro con brio\nII. Andante con moto\nIII. Scherzo",
            "placed at the pauses in the audio"),
          example("A programme with durations", "Giuseppe Verdi\nDon Carlos – 'O don fatale'(5 mins)\nAida – Triumphal March(5 mins)",
            "as the BBC lists them: placed by the durations and the pauses"),
          example("A table", "Zeit\tKomponist\tWerk\n0:00\tJohann Strauss\tDonauwalzer",
            "tabs, ; | or commas; start or duration, composer, title — a header row is optional"),
          example("CUE sheet", "TRACK 01 AUDIO\n  TITLE \"Overture\"\n  INDEX 01 00:00:00", ""),
          example("JSON", "{\"chapters\": [{\"tc_start\": 63, \"name\": \"Overture\"}]}",
            "this plugin's own export, medici.tv, ffprobe, yt-dlp, Stash"),
          example("Subtitles", "00:00:42,000 --> 00:00:47,000\nWir beginnen mit Franz von Suppè: Fatinitza-Marsch",
            "SRT or WebVTT: announcements and title cards become markers")),
        readmeLink()));
  }

  // Text scrapers: paste the text, or pick a file (read in the browser, so
  // from this device), check and edit it, then scrape.
  function textDialog(scraper) {
    const dialog = openDialog(`Scrape markers — ${scraper.name}`);
    const area = el("textarea", {
      className: "form-control",
      rows: 16,
      spellcheck: false,
      placeholder: scraper.description
        ? "I. Allegro con brio\nII. Andante con moto\nIII. Scherzo\n…"
        : "0:00 I. Allegro con brio\n7:41 II. Andante con moto\n17:30 - 23:02 III. Scherzo\n…",
      style: { fontFamily: "monospace", fontSize: "0.9em" },
    });
    const file = el("input", {
      type: "file",
      accept: ".txt,.cue,.md,.csv,.tsv,.json,.srt,.vtt,text/*,application/json",
      className: "form-control-file",
      onchange: () => {
        const f = file.files && file.files[0];
        if (!f) return;
        const reader = new FileReader();
        reader.onload = () => { area.value = decodeText(new Uint8Array(reader.result)); };
        reader.readAsArrayBuffer(f);
      },
    });
    dialog.body.append(
      scraper.description
        ? el("p", { className: "small text-muted" }, scraper.description, " ", readmeLink())
        : formatsHelp(),
      el("div", { className: "mb-2" }, file),
      area
    );
    const go = el("button", { type: "button", className: "btn btn-primary", textContent: "Scrape",
      onclick: () => {
        if (!area.value.trim()) return area.focus();
        scrape(scraper, null, area.value);
      } });
    dialog.footer.prepend(go);
    setTimeout(() => area.focus(), 0);
  }

  async function scrape(scraper, url, text) {
    const dialog = openDialog(`Scrape markers — ${scraper.name}`);
    // How long it's been working — reading the audio for the pauses (titles
    // without times) can take minutes on a long concert and a small server.
    const status = el("p", {});
    const hint = el("p", { className: "small text-muted" });
    const began = Date.now();
    const tick = () => {
      const s = Math.round((Date.now() - began) / 1000);
      status.textContent = `${url ? `Scraping ${url}` : "Scraping"} … ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
      if (s >= 8 && scraper.id === "frames_ocr") {
        hint.textContent = "Still working. It reads the picture where pieces begin — the start and the 45 seconds after " +
          "each pause in the audio, a frame every 4 seconds. For a long concert that can take several minutes the first " +
          "time (it's remembered for the next time). Closing this dialog doesn't stop it.";
      } else if (s >= 8) {
        hint.textContent = "Still working. Finding the pauses in the audio reads the whole soundtrack — for a long concert " +
          "that can take a few minutes the first time (it's remembered for the next time). Closing this dialog doesn't stop it.";
      }
    };
    tick();
    const timer = setInterval(() => { if (!status.isConnected) clearInterval(timer); else tick(); }, 1000);
    // How far a long scraper is (Text in the picture says it) — asked every
    // few seconds, shown as a bar.
    const bar = el("div", { className: "progress-bar", style: { width: "0%" } });
    const barBox = el("div", { className: "progress mb-1", style: { display: "none", height: "8px" } }, bar);
    const barText = el("div", { className: "small text-muted mb-2" });
    const watch = scraper.id === "frames_ocr" && !text ? watchProgress((p) => {
      if (!status.isConnected) return;
      const pct = p.total ? Math.min(100, Math.round((100 * p.done) / p.total)) : null;
      barBox.style.display = pct == null ? "none" : "";
      bar.style.width = `${pct || 0}%`;
      barText.textContent = p.phase === "scan"
        ? `Looking at the picture (where pieces begin): ${formatTime(p.done)}${p.total ? ` of ${formatTime(p.total)} (${pct} %)` : ""}`
        : p.phase === "compare" ? `Looking for text in the picture … ${pct} %`
        : p.phase === "read" ? `Reading the picture where pieces begin: frame ${p.done} of ${p.total} (${pct} %)`
        : "";
    }) : null;
    dialog.body.append(status, barBox, barText, hint);
    let result;
    let settings = {};
    try {
      const [res, conf] = await Promise.all([
        runOperation({ mode: "marker_scrape", scraper: scraper.id, scene_id: sceneId(), url: url || "", text: text || "" }),
        gql("query { configuration { plugins } }").catch(() => null),
      ]);
      result = res;
      const plugins = (conf && conf.configuration.plugins) || {};
      settings = { ...(plugins[OLD_PLUGIN_ID] || {}), ...(plugins[PLUGIN_ID] || {}) };
    } catch (err) {
      clearInterval(timer);
      if (err.lost && watch && watch.running()) {
        // The scanner's still at it on the server: keep showing how far it
        // is, and fetch the result (remembered by then) when it's done.
        hint.textContent = "Lost the connection to the scanner, but it's still working on the server — " +
          "the result is fetched when it's done.";
        watch.whenDone(() => { if (status.isConnected) scrape(scraper, url, text); });
        return;
      }
      if (watch) watch.stop();
      if (err.lost) {
        const s = Math.round((Date.now() - began) / 1000);
        dialog.body.replaceChildren(
          el("div", { className: "alert alert-warning", style: { whiteSpace: "pre-wrap" }, textContent:
            `${err.message}\nLost the connection to the scanner after ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} — ` +
            "the scraper may still be working on the server. What it has read (the audio, the picture) is remembered, " +
            "so trying again once it's done is much quicker." }),
          el("button", { type: "button", className: "btn btn-secondary", textContent: "Try again",
            onclick: () => scrape(scraper, url, text) }));
        return;
      }
      const message = String(err.message || err);
      // A scraper that said why it found nothing is turned off in the menu
      // for this scene; one that crashed or timed out isn't.
      if (!text && / failed: /.test(message) && !/Traceback|timed out|TimeoutExpired/.test(message)) {
        foundNothing.set(nothingKey(scraper.id, url), message.split(" failed: ").pop().trim());
      }
      dialog.body.replaceChildren(el("div", { className: "alert alert-danger", style: { whiteSpace: "pre-wrap" }, textContent: message }));
      return;
    }
    clearInterval(timer);
    if (watch) watch.stop();
    if (!result.markers.length) {
      if (!text) foundNothing.set(nothingKey(scraper.id, url), result.notes || "nothing found"); // off in the menu now
      dialog.body.replaceChildren(el("p", { textContent: result.notes || "No markers found." }));
      return;
    }
    review(dialog, result, (settings.scrapedMarkerTag || "").trim() || DEFAULT_PRIMARY, settings.skipPauseCheck !== true);
  }

  // Asks the server every 3 s how far the scraper for this scene is
  // (marker_progress). A "done" left from an earlier run isn't taken for
  // this one's.
  function watchProgress(show) {
    const scene = sceneId();
    let first = null;
    let last = null;
    let stopped = false;
    let onDone = null;
    const poll = async () => {
      if (stopped) return;
      let p = null;
      try { p = await runOperation({ mode: "marker_progress", scene_id: scene }); } catch (e) { /* ask again */ }
      if (stopped) return;
      if (p && first === null) first = p.updated;
      if (p && !(p.phase === "done" && p.updated === first)) {
        last = p;
        if (p.phase === "done") {
          if (onDone) { stopped = true; onDone(); return; }
        } else {
          show(p);
        }
      }
      setTimeout(poll, 3000);
    };
    setTimeout(poll, 1500);
    return {
      stop: () => { stopped = true; },
      running: () => !!last && last.phase !== "done",
      whenDone: (fn) => { onDone = fn; },
    };
  }

  function openDialog(title) {
    const old = document.getElementById(DIALOG_ID);
    if (old) old.remove();
    const close = () => wrapper.remove();
    const body = el("div", { className: "modal-body", style: { maxHeight: "70vh", overflowY: "auto" } });
    const footer = el("div", { className: "modal-footer" },
      el("button", { type: "button", className: "btn btn-secondary", textContent: "Close", onclick: close }));
    const wrapper = el("div", { id: DIALOG_ID },
      el("div", { className: "modal-backdrop show", onclick: close }),
      el("div", { className: "modal d-block", tabIndex: -1, onclick: (e) => { if (e.target === e.currentTarget) close(); } },
        el("div", { className: "modal-dialog modal-xl" },
          el("div", { className: "modal-content" },
            el("div", { className: "modal-header" }, el("h5", { className: "modal-title", textContent: title })),
            body,
            footer))));
    document.body.appendChild(wrapper);
    return { body, footer, close };
  }

  // -- the check against the audio ------------------------------------------------------
  //
  // The pauses in the scene's audio (see pauses.py) are where pieces and
  // movements usually start. Every marker is compared with them: does it
  // start where the music starts again? If most would with all times
  // shifted, that shift is suggested; markers a little off can be snapped
  // onto their pause.

  const AT_PAUSE = 3; // seconds: counts as starting at the pause
  const NEAR_PAUSE = 20; // seconds: close enough to snap
  const MAX_SHIFT = 900; // seconds: largest shift suggested

  // Where the music starts: at its very beginning, and after every pause.
  function resumePoints(audio) {
    return [audio.music_start, ...audio.pauses.map((p) => p[1])];
  }

  function nearest(points, t) {
    let best = null;
    points.forEach((p) => { if (best == null || Math.abs(p - t) < Math.abs(best - t)) best = p; });
    return best == null ? null : best - t; // + = the pause is later
  }

  // The shift that lets the most markers start at a pause (ties: the one
  // that fits them most closely), and how many fit then.
  function bestShift(points, starts) {
    const fit = (shift) => {
      let count = 0;
      let spread = 0;
      starts.forEach((s) => {
        const d = Math.abs(nearest(points, s + shift));
        if (d <= AT_PAUSE) { count++; spread += d; }
      });
      return { shift, count, spread };
    };
    let best = fit(0);
    starts.forEach((s) => points.forEach((p) => {
      const shift = Math.round((p - s) * 10) / 10;
      if (Math.abs(shift) > MAX_SHIFT) return;
      const f = fit(shift);
      if (f.count > best.count || (f.count === best.count && f.spread < best.spread - 0.5)) best = f;
    }));
    return best;
  }

  // -- placing titles at the pauses again ------------------------------------------------
  //
  // Titles placed at the pauses (titles without times) can be placed again
  // when parts are marked as not music: those parts become breaks of their
  // own (with the pauses right next to them), and the remaining breaks are
  // the longest pauses — as many as it takes for one piece per title.
  // Returns [{ seconds, end_seconds, piece }] and [{ seconds, end_seconds,
  // notMusic: true }], in order, and how many titles got no piece.
  function placePieces(count, audio, skips) {
    const near = 1.5;
    const merged = skips.map(([s, e]) => {
      let a = s;
      let b = e;
      audio.pauses.forEach(([ps, pe]) => {
        if (pe >= a - near && ps <= a + near) a = Math.min(a, ps);
        if (ps <= b + near && pe >= b - near) b = Math.max(b, pe);
      });
      return [a, b];
    });
    const free = audio.pauses.filter(([ps, pe]) => !merged.some(([a, b]) => pe >= a - 0.5 && ps <= b + 0.5));
    const need = Math.max(0, count - 1);
    const breaks = [...merged.map((g) => ({ g, skip: true }))];
    free.slice().sort((x, y) => (y[1] - y[0]) - (x[1] - x[0])).forEach((g) => {
      // as many breaks as pieces need — a not-music part at the very start
      // or end of the music doesn't separate two pieces, so it doesn't count
      const inner = breaks.filter((x) => x.g[0] > audio.music_start + near && x.g[1] < audio.music_end - near).length;
      if (inner < need) breaks.push({ g, skip: false });
    });
    breaks.sort((x, y) => x.g[0] - y.g[0]);
    const out = [];
    let start = audio.music_start;
    let piece = 0;
    const addPiece = (s, e) => {
      if (e - s < 1 || piece >= count) return;
      out.push({ seconds: s, end_seconds: e, piece: piece++ });
    };
    breaks.forEach(({ g, skip }) => {
      addPiece(start, g[0]);
      if (skip) out.push({ seconds: g[0], end_seconds: g[1], notMusic: true });
      start = Math.max(start, g[1]);
    });
    addPiece(start, audio.music_end);
    return { rows: out, missing: count - piece };
  }

  // -- copying markers as text ----------------------------------------------------------------
  //
  // Markers as text to paste or save elsewhere: a tracklist (YouTube
  // chapters; the Plain text scraper reads it back), with end times, a
  // table for a spreadsheet, a CUE sheet, or ffmpeg chapters (ffmpeg can
  // write those into a video file). items: [{ seconds, end_seconds, title,
  // tags }], in time order.

  function clock(t, hours) {
    const s = Math.max(0, Math.round(t));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = String(s % 60).padStart(2, "0");
    return hours ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
  }

  const EXPORTS = {
    tracklist: { label: "Tracklist (0:00 Title)", ext: "txt" },
    ranges: { label: "With end times (0:00 – 5:12 Title)", ext: "txt" },
    table: { label: "Table, tab-separated (for a spreadsheet)", ext: "tsv" },
    cue: { label: "CUE sheet (everything — Plain text reads it back)", ext: "cue" },
    ffmeta: { label: "ffmpeg chapters (ffmetadata)", ext: "ffmetadata" },
    json: { label: "JSON (everything — Plain text reads it back)", ext: "markers.json" },
  };

  function exportText(format, items, withTags, info) {
    const hours = items.some((m) => (m.end_seconds || m.seconds) >= 3600);
    const label = (m) => (withTags && m.tags && m.tags.length ? `${m.tags.join(", ")} – ${m.title}` : m.title) || "";
    const endOf = (m, i) => (m.end_seconds != null ? m.end_seconds : (items[i + 1] ? items[i + 1].seconds : info.duration || null));
    if (format === "ranges") {
      return items.map((m, i) => {
        const e = endOf(m, i);
        return `${clock(m.seconds, hours)}${e != null ? ` – ${clock(e, hours)}` : ""} ${label(m)}`;
      }).join("\n");
    }
    if (format === "table") {
      return ["Start\tEnd\tTitle\tTags", ...items.map((m, i) => {
        const e = endOf(m, i);
        return [clock(m.seconds, true), e != null ? clock(e, true) : "", m.title || "", (m.tags || []).join(", ")]
          .map((c) => String(c).replace(/[\t\n]/g, " ")).join("\t");
      })].join("\n");
    }
    if (format === "cue") {
      const q = (t) => String(t || "").replace(/"/g, "'");
      const frames = (t) => {
        const f = Math.round(Math.max(0, t) * 75);
        return `${String(Math.floor(f / 4500)).padStart(2, "0")}:${String(Math.floor(f / 75) % 60).padStart(2, "0")}:${String(f % 75).padStart(2, "0")}`;
      };
      const lines = [];
      if (info.title) lines.push(`TITLE "${q(info.title)}"`);
      lines.push(`FILE "${q(info.file || "video")}" WAVE`);
      // Everything, so the CUE reader gets back what went in: the title as
      // it is, the first tag as PERFORMER (players show "Performer –
      // Title"), and in REM lines (which players skip) the primary tag,
      // all tags and the end.
      items.forEach((m, i) => {
        const e = endOf(m, i);
        lines.push(`  TRACK ${String(i + 1).padStart(2, "0")} AUDIO`);
        lines.push(`    TITLE "${q(m.title)}"`);
        if (m.tags && m.tags.length) lines.push(`    PERFORMER "${q(m.tags[0])}"`);
        if (m.primary_tag) lines.push(`    REM PRIMARY_TAG "${q(m.primary_tag)}"`);
        if (m.tags && m.tags.length) lines.push(`    REM TAGS "${q(m.tags.join("; "))}"`);
        if (e != null) lines.push(`    REM END ${frames(e)}`);
        lines.push(`    INDEX 01 ${frames(m.seconds)}`);
      });
      return lines.join("\n");
    }
    if (format === "json") {
      // Everything, field by field: Plain text (and a chapter file
      // "<video>.markers.json") read it back as it is.
      return JSON.stringify({
        version: 1,
        title: info.title || undefined,
        file: info.file || undefined,
        markers: items.map((m) => ({
          seconds: Math.round(m.seconds * 1000) / 1000,
          end_seconds: m.end_seconds == null ? null : Math.round(m.end_seconds * 1000) / 1000,
          title: m.title || "",
          primary_tag: m.primary_tag || "",
          tags: m.tags || [],
        })),
      }, null, 2);
    }
    if (format === "ffmeta") {
      const esc = (t) => String(t || "").replace(/([=;#\\\n])/g, "\\$1");
      const lines = [";FFMETADATA1"];
      if (info.title) lines.push(`title=${esc(info.title)}`);
      items.forEach((m, i) => {
        const e = endOf(m, i);
        lines.push("", "[CHAPTER]", "TIMEBASE=1/1000", `START=${Math.round(m.seconds * 1000)}`,
          `END=${Math.round((e != null ? e : m.seconds) * 1000)}`, `title=${esc(label(m))}`);
      });
      return lines.join("\n");
    }
    return items.map((m) => `${clock(m.seconds, hours)} ${label(m)}`).join("\n");
  }

  // Copy: the clipboard API needs https (Stash usually runs on plain http
  // in the home network), so the old way is the fallback.
  async function copyText(text, area) {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (e) {
      // the old way, then
    }
    area.focus();
    area.select();
    try {
      return document.execCommand("copy");
    } catch (e) {
      return false;
    }
  }

  // The panel: format, tags before the title, the text, Copy and Download.
  function exportPanel(getItems, getInfo) {
    const format = el("select", { className: "form-control form-control-sm d-inline-block", style: { width: "auto" } },
      ...Object.entries(EXPORTS).map(([k, v]) => el("option", { value: k, textContent: v.label })));
    const withTags = el("input", { type: "checkbox", checked: true });
    const area = el("textarea", { className: "form-control", rows: 10, readOnly: true, spellcheck: false,
      style: { fontFamily: "monospace", fontSize: "0.85em", whiteSpace: "pre" } });
    const status = el("span", { className: "small ml-2" });
    const update = () => { area.value = exportText(format.value, getItems(), withTags.checked, getInfo()); status.textContent = ""; };
    format.addEventListener("change", update);
    withTags.addEventListener("change", update);
    const copy = el("button", { type: "button", className: "btn btn-sm btn-secondary", textContent: "Copy",
      onclick: async () => {
        update();
        const ok = await copyText(area.value, area);
        status.textContent = ok ? "Copied." : "Couldn't copy — the text is selected: press Ctrl+C / ⌘C.";
        status.className = `small ml-2 ${ok ? "text-success" : "text-warning"}`;
      } });
    const download = el("button", { type: "button", className: "btn btn-sm btn-secondary ml-2", textContent: "Download",
      onclick: () => {
        update();
        const info = getInfo();
        const base = (info.file || info.title || "markers").replace(/\.[^.]+$/, "") || "markers";
        const a = el("a", { href: URL.createObjectURL(new Blob([area.value], { type: "text/plain;charset=utf-8" })),
          download: `${base}.${EXPORTS[format.value].ext}` });
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      } });
    const panel = el("div", { className: "mac-export mt-3 p-2", style: { border: "1px solid rgba(128,128,128,.4)", borderRadius: "4px" } },
      el("div", { className: "mb-2 d-flex flex-wrap align-items-center", style: { gap: "1em" } },
        el("strong", { textContent: "As text" }), format,
        el("label", { className: "mb-0" }, withTags, " Tags before the title")),
      area,
      el("div", { className: "mt-2" }, copy, download, status));
    panel.refresh = update;
    update();
    return panel;
  }

  // -- composers in the titles of the scene's markers ----------------------------------------
  //
  // For the markers the scene already has: composer tags named in a title
  // are added to the marker, and the title loses the names (see
  // marker_composers in marker_scrapers.py). Shown first, applied for the
  // ticked ones.
  // The old title with what goes struck through and the rest as it is:
  // the longest common subsequence of characters between old and new.
  function struckTitle(before, after) {
    if (before === after) return el("span", { textContent: before });
    const a = Array.from(before);
    const b = Array.from(after);
    const n = a.length;
    const m = b.length;
    const keep = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        keep[i][j] = a[i] === b[j] ? keep[i + 1][j + 1] + 1 : Math.max(keep[i + 1][j], keep[i][j + 1]);
      }
    }
    const parts = []; // [text, removed?]
    const push = (ch, removed) => {
      const last = parts[parts.length - 1];
      if (last && last[1] === removed) last[0] += ch;
      else parts.push([ch, removed]);
    };
    let i = 0;
    let j = 0;
    while (i < n) {
      if (j < m && a[i] === b[j]) { push(a[i], false); i++; j++; }
      else if (j < m && keep[i][j + 1] >= keep[i + 1][j]) { j++; } // only in the new title (tidying): skip
      else { push(a[i], true); i++; }
    }
    return el("span", {}, ...parts.map(([text, removed]) => removed
      ? el("span", { textContent: text, style: { textDecoration: "line-through", color: "#e57373" } })
      : el("span", { textContent: text })));
  }

  async function composersDialog() {
    const dialog = openDialog("Composers from the marker titles");
    const footerButtons = [];
    const clearFooter = () => { footerButtons.forEach((b) => b.remove()); footerButtons.length = 0; };
    const addFooter = (button) => { footerButtons.push(button); dialog.footer.prepend(button); };

    const load = async () => {
      clearFooter();
      dialog.body.replaceChildren(el("p", { textContent: "Looking …" }));
      let result;
      try {
        result = await runOperation({ mode: "marker_composers", scene_id: sceneId() });
      } catch (err) {
        dialog.body.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
        return;
      }
      const parts = [];
      const missing = result.missing || [];
      if (missing.length) parts.push(await missingSection(missing));
      const proposals = result.proposals || [];
      if (proposals.length) {
        parts.push(proposalsSection(proposals));
      } else if (!missing.length) {
        parts.push(el("p", { textContent: result.notes ||
          "Nothing to change: no marker title names a composer tag it doesn't have, and the titles are clean." }));
      }
      dialog.body.replaceChildren(...parts);
      addFooter(el("button", { type: "button", className: "btn btn-secondary mr-auto", textContent: "New composer…",
        onclick: () => newComposerDialog() }));
    };

    // Names before the separator that aren't composers yet: look each up
    // with the Classical Music scraper, pick, import.
    const missingSection = async (missing) => {
      const box = el("div", { className: "mb-4 p-2", style: { border: "1px solid rgba(128,128,128,.4)", borderRadius: "4px" } });
      const scraperId = await performerScraperId().catch(() => null);
      box.append(el("strong", { textContent: "Import missing artists" }),
        el("p", { className: "small text-muted mb-2", textContent:
          "Names in the titles that aren't artists in Stash yet. Pick the right person for each on Wikidata — the performer " +
          "is created (portrait, dates, Wikipedia text, and the name as the titles have it as an alias), and Tag Improvements " +
          "makes their tag: under Composers if ticked as a composer, else where their roles put them (e.g. Soloists). " +
          "Then the titles below are worked out again." }));
      if (!scraperId) {
        box.append(el("div", { className: "alert alert-warning mb-0", textContent:
          "The Classical Music performer scraper isn't installed (Settings → Metadata Providers → Available Scrapers)." }));
        return box;
      }
      const rows = [];
      const tbody = el("tbody");
      for (const item of missing) {
        const check = el("input", { type: "checkbox", checked: true });
        const select = el("select", { className: "form-control form-control-sm" }, el("option", { textContent: "Searching Wikidata …" }));
        const composerBox = el("input", { type: "checkbox", checked: false });
        const state = el("div", { className: "small text-muted" });
        tbody.append(el("tr", {}, el("td", {}, check),
          el("td", {}, el("strong", { textContent: item.name }),
            el("div", { className: "small text-muted", textContent: `${item.count} marker${item.count === 1 ? "" : "s"}` })),
          el("td", { style: { width: "62%" } },
            el("div", { className: "d-flex align-items-center" }, select,
              el("label", { className: "small mb-0 ml-2", style: { whiteSpace: "nowrap" } }, composerBox, " is a composer")),
            state)));
        const row = { item, check, select, composerBox, state, found: [] };
        const describe = () => {
          const p = row.found[Number(select.value)];
          state.textContent = !check.checked || !p ? "→ not imported."
            : composerBox.checked ? `→ ${p.name} is created, tagged Composer — tag under Composers.`
              : `→ ${p.name} is created — tag where the roles put it (e.g. Soloists).`;
        };
        [check, select, composerBox].forEach((x) => x.addEventListener("change", describe));
        row.describe = describe;
        rows.push(row);
        searchPerformers(scraperId, item.query).then((found) => {
          row.found = found;
          select.replaceChildren(el("option", { value: "", textContent: found.length ? "— don't import —" : "Nothing found" }),
            ...found.map((p, i) => el("option", { value: String(i), textContent: `${p.name}${p.disambiguation ? ` — ${p.disambiguation}` : ""}` })));
          // "… Sohn" / "… Vater" in the title: the junior / senior one first.
          const generation = /\b(sohn|jun\.?|junior|ii|jr\.?)\b/i.test(item.name) ? /junior|jüngere|\bii\b|jr|sohn/i
            : /\b(vater|sen\.?|senior|i)\b/i.test(item.name) ? /senior|ältere|\bi\b|vater/i : null;
          const isComposer = (p) => COMPOSER_WORDS.test(p.disambiguation || "");
          let best = generation ? found.findIndex((p) => isComposer(p) && generation.test(`${p.name} ${p.disambiguation || ""}`)) : -1;
          if (best < 0) best = found.findIndex(isComposer);
          select.value = found.length ? String(best >= 0 ? best : 0) : "";
          composerBox.checked = best >= 0;
          if (!found.length) check.checked = false;
          describe();
        }).catch((err) => {
          select.replaceChildren(el("option", { value: "", textContent: `Search failed: ${err.message || err}` }));
          check.checked = false;
          describe();
        });
      }
      const status = el("div", { className: "small mt-2" });
      const importButton = el("button", { type: "button", className: "btn btn-primary btn-sm", textContent: "Import selected",
        onclick: async () => {
          const chosen = rows.filter((r) => r.check.checked && r.select.value !== "" && r.found[Number(r.select.value)]);
          if (!chosen.length) return;
          importButton.disabled = true;
          const done = [];
          for (const r of chosen) {
            const p = r.found[Number(r.select.value)];
            r.state.className = "small";
            r.state.textContent = `Getting ${p.name} from Wikidata and creating the performer …`;
            try {
              const res = await createComposer(scraperId, p, r.item.name, r.composerBox.checked);
              done.push(res.name);
              r.state.className = "small text-success";
              r.state.textContent = res.existed ? `✓ ${res.name} was there already${r.composerBox.checked ? " — now tagged Composer" : ""}.`
                : `✓ ${res.name} created${r.composerBox.checked ? ", tagged Composer" : ""}.`;
            } catch (err) {
              r.state.className = "small text-danger";
              r.state.textContent = `✗ ${err.message || err}`;
            }
          }
          // Tag Improvements makes the tags as the performers are saved (a
          // hook, run by the server): give it a moment, then look again.
          status.textContent = done.length ? `Imported ${done.join(", ")} — waiting for their tags …` : "Nothing imported.";
          for (let i = 0; i < 8; i++) {
            await new Promise((r) => setTimeout(r, 1000));
            const again = await runOperation({ mode: "marker_composers", scene_id: sceneId() }).catch(() => null);
            if (again && (again.missing || []).length < missing.length) break;
          }
          load();
        } });
      box.append(el("table", { className: "table table-sm mb-1" }, tbody), importButton, status);
      return box;
    };

    // What changes in the titles and tags.
    const proposalsSection = (proposals) => {
      const picked = new Set(proposals.map((p) => p.id));
      const rows = proposals.map((p) => el("tr", {},
        el("td", {}, el("input", { type: "checkbox", checked: true,
          onchange: (e) => { if (e.target.checked) picked.add(p.id); else picked.delete(p.id); } })),
        el("td", { style: { whiteSpace: "nowrap" } }, formatTime(p.seconds || 0)),
        el("td", {}, struckTitle(p.title, p.new_title)),
        el("td", {}, p.add_tags.length ? el("span", { className: "text-success", textContent: `+ ${p.add_tags.join(", ")}` }) : "")));
      const apply = el("button", { type: "button", className: "btn btn-primary", textContent: "Apply",
        onclick: async () => {
          if (!picked.size) return;
          apply.disabled = true;
          apply.textContent = "Applying…";
          try {
            const done = await runOperation({ mode: "marker_composers", scene_id: sceneId(), apply: "true", ids: JSON.stringify([...picked]) });
            clearFooter();
            dialog.body.replaceChildren(el("div", { className: "alert alert-success",
              textContent: `${done.applied} marker${done.applied === 1 ? "" : "s"} changed.` }));
            await refreshStash();
          } catch (err) {
            apply.disabled = false;
            apply.textContent = "Apply";
            dialog.body.prepend(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
          }
        } });
      addFooter(apply);
      return el("div", {},
        el("p", { className: "small text-muted", textContent:
          "Composer tags named in a marker's title — by name, alias or surname — are added to it, and the title loses the names. " +
          "Primary tag, times and other tags stay." }),
        el("table", { className: "table table-sm" },
          el("thead", {}, el("tr", {}, el("th", {}), el("th", {}, "Time"), el("th", {}, "Title"), el("th", {}, "Tags"))),
          el("tbody", {}, ...rows)));
    };

    load();
  }

  // -- a new composer, from the Classical Music performer scraper ------------------------------
  //
  // Enter a name, pick the right one of the scraper's results, and the
  // performer is created with everything the scraper fills in — and the
  // performer tag that marks composers ("Composer", Tag Improvements'
  // "Composer performer tag" setting), so Tag Improvements makes the
  // composer tag. A performer who exists already just gets that tag.

  async function performerScraperId() {
    const data = await gql("query { listScrapers(types: [PERFORMER]) { id name } }");
    const found = (data.listScrapers || []).find((s) => /classical\s*music/i.test(`${s.id} ${s.name}`));
    return found ? found.id : null;
  }

  async function tagIdFor(name, create) {
    const data = await gql(
      "query($n: String!) { findTags(tag_filter: { name: { value: $n, modifier: EQUALS } }, filter: { per_page: 1 }) { tags { id } } }",
      { n: name });
    const tag = data.findTags.tags[0];
    if (tag) return String(tag.id);
    const alias = await gql(
      "query($n: String!) { findTags(tag_filter: { aliases: { value: $n, modifier: EQUALS } }, filter: { per_page: 1 }) { tags { id } } }",
      { n: name }).catch(() => ({ findTags: { tags: [] } }));
    if (alias.findTags.tags[0]) return String(alias.findTags.tags[0].id);
    if (!create) return null;
    const made = await gql("mutation($input: TagCreateInput!) { tagCreate(input: $input) { id } }", { input: { name } });
    return String(made.tagCreate.id);
  }

  async function composerTagName() {
    try {
      const conf = await gql("query { configuration { plugins } }");
      const raw = ((conf.configuration.plugins || {}).tagTree || {}).composerPerformerTag;
      const name = (raw == null ? "" : String(raw)).trim();
      return name && name !== "-" ? name : "Composer";
    } catch (e) {
      return "Composer";
    }
  }

  // Creates the composer for a search result of the Classical Music
  // scraper (or tags an existing performer): returns { id, name, existed }.
  // extraAlias: a spelling to add (the name as the marker titles have it),
  // so the composer tag made from it matches them exactly.
  async function createComposer(scraperId, picked, extraAlias, asComposer = true) {
    const full = (await gql(
      "query($s: ScraperSourceInput!, $i: ScrapeSinglePerformerInput!) { scrapeSinglePerformer(source: $s, input: $i) { " +
      "name aliases urls birthdate death_date gender country details images tags { name stored_id } } }",
      { s: { scraper_id: scraperId }, i: { performer_input: { name: picked.name, urls: picked.urls || [] } } }
    )).scrapeSinglePerformer[0];
    if (!full) throw new Error(`The scraper returned nothing for ${picked.name}.`);
    // Not a composer (a soloist, a conductor …): no Composer tag — the tags
    // Wikidata gives (Pianist, Soprano …) decide where Tag Improvements files it.
    const marker = asComposer ? await composerTagName() : null;
    const markerId = asComposer ? await tagIdFor(marker, true) : null;
    // Already there? Stash compares names regardless of case and accents —
    // look the same way, so it isn't created twice.
    const plainName = (t) => (t || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();
    const candidates = (await gql(
      "query($n: String!) { findPerformers(performer_filter: { name: { value: $n, modifier: INCLUDES } }, filter: { per_page: 50 }) { performers { id name alias_list tags { id } } } }",
      { n: full.name.split(/\s+/).pop() })).findPerformers.performers;
    const existing = candidates.find((p) => plainName(p.name) === plainName(full.name)) || null;
    if (existing) {
      const ids = [...new Set([...existing.tags.map((t) => String(t.id)), ...(markerId ? [markerId] : [])])];
      const aliases = extraAlias && extraAlias !== existing.name && !(existing.alias_list || []).includes(extraAlias)
        ? [...(existing.alias_list || []), extraAlias] : null;
      await gql("mutation($input: PerformerUpdateInput!) { performerUpdate(input: $input) { id } }",
        { input: { id: existing.id, tag_ids: ids, ...(aliases ? { alias_list: aliases } : {}) } });
      return { id: existing.id, name: existing.name, existed: true, marker };
    }
    const tagIds = markerId ? [markerId] : [];
    for (const t of full.tags || []) {
      const id = t.stored_id ? String(t.stored_id) : await tagIdFor(t.name, true);
      if (id && !tagIds.includes(id)) tagIds.push(id);
    }
    const aliasList = (full.aliases || "").split(",").map((a) => a.trim()).filter(Boolean);
    if (extraAlias && extraAlias !== full.name && !aliasList.includes(extraAlias)) aliasList.push(extraAlias);
    const input = { name: full.name, alias_list: aliasList, urls: full.urls || [], tag_ids: tagIds };
    if (full.birthdate) input.birthdate = full.birthdate;
    if (full.death_date) input.death_date = full.death_date;
    if (full.gender) input.gender = full.gender;
    if (full.country) input.country = full.country;
    if (full.details) input.details = full.details;
    if (full.images && full.images.length) input.image = full.images[0];
    const made = await gql("mutation($input: PerformerCreateInput!) { performerCreate(input: $input) { id name } }", { input });
    return { id: made.performerCreate.id, name: made.performerCreate.name, existed: false, marker };
  }

  async function searchPerformers(scraperId, query) {
    const data = await gql(
      "query($s: ScraperSourceInput!, $i: ScrapeSinglePerformerInput!) { scrapeSinglePerformer(source: $s, input: $i) { name disambiguation urls } }",
      { s: { scraper_id: scraperId }, i: { query } });
    return data.scrapeSinglePerformer || [];
  }

  const COMPOSER_WORDS = /komponist|composer|compositeur|compositore|compositor|kapellmeister/i;

  async function newComposerDialog() {
    const dialog = openDialog("New composer");
    const scraperId = await performerScraperId().catch(() => null);
    if (!scraperId) {
      dialog.body.append(el("div", { className: "alert alert-warning", textContent:
        "The Classical Music performer scraper isn't installed: Settings → Metadata Providers → Available Scrapers, " +
        "source https://rokdd.github.io/stash-classicmusic-plugins/main/scrapers/index.yml." }));
      return;
    }
    const input = el("input", { type: "text", className: "form-control", placeholder: "Name — a surname is enough: Strauss, Rachmaninow …" });
    const results = el("div", { className: "mt-3" });
    const status = el("div", { className: "mt-2" });
    const search = async () => {
      const query = input.value.trim();
      if (!query) return;
      results.replaceChildren(el("p", { className: "text-muted", textContent: "Searching …" }));
      try {
        const data = await gql(
          "query($s: ScraperSourceInput!, $i: ScrapeSinglePerformerInput!) { scrapeSinglePerformer(source: $s, input: $i) { name disambiguation urls } }",
          { s: { scraper_id: scraperId }, i: { query } });
        const found = data.scrapeSinglePerformer || [];
        if (!found.length) {
          results.replaceChildren(el("p", { textContent: "Nothing found." }));
          return;
        }
        results.replaceChildren(el("div", { className: "list-group" }, ...found.map((p) =>
          el("button", { type: "button", className: "list-group-item list-group-item-action text-left",
            onclick: () => create(p) },
            el("strong", { textContent: p.name }),
            p.disambiguation ? el("div", { className: "small text-muted", textContent: p.disambiguation }) : null))));
      } catch (err) {
        results.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
      }
    };
    const create = async (picked) => {
      results.replaceChildren();
      status.replaceChildren(el("p", { className: "text-muted", textContent: `Getting ${picked.name} …` }));
      try {
        const done = await createComposer(scraperId, picked, null);
        status.replaceChildren(el("div", { className: "alert alert-success" },
          done.existed
            ? `${done.name} was there already and is now tagged ${done.marker}. `
            : `${done.name} created, tagged ${done.marker} — Tag Improvements makes the composer tag. `,
          el("a", { href: `/performers/${done.id}`, textContent: "Open" })));
      } catch (err) {
        status.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
      }
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });
    dialog.body.append(
      el("div", { className: "d-flex", style: { gap: "8px" } }, input,
        el("button", { type: "button", className: "btn btn-primary", textContent: "Search", onclick: search })),
      results, status);
    setTimeout(() => input.focus(), 0);
  }

  // The scene's own markers, as text (from the Scrape markers menu).
  async function copySceneMarkers() {
    const dialog = openDialog("Copy markers as text");
    dialog.body.append(el("p", { textContent: "Loading …" }));
    try {
      const [data, media] = await Promise.all([
        gql("query($id: ID!) { findScene(id: $id) { scene_markers { seconds end_seconds title primary_tag { name } tags { name } } } }",
          { id: sceneId() }).catch(() =>
          gql("query($id: ID!) { findScene(id: $id) { scene_markers { seconds title primary_tag { name } tags { name } } } }", { id: sceneId() })),
        sceneMedia().catch(() => ({})),
      ]);
      const items = ((data.findScene || {}).scene_markers || [])
        .map((m) => ({ seconds: m.seconds, end_seconds: m.end_seconds == null ? null : m.end_seconds,
          title: m.title || (m.primary_tag || {}).name || "", primary_tag: (m.primary_tag || {}).name || "",
          tags: (m.tags || []).map((t) => t.name) }))
        .sort((a, b) => a.seconds - b.seconds);
      if (!items.length) {
        dialog.body.replaceChildren(el("p", { textContent: "This scene has no markers yet." }));
        return;
      }
      dialog.body.replaceChildren(exportPanel(() => items, () => media));
    } catch (err) {
      dialog.body.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
    }
  }

  // -- the scene: length and pictures for the preview -------------------------------------

  async function sceneMedia() {
    const data = await gql(
      "query($id: ID!) { findScene(id: $id) { title files { duration path } paths { vtt sprite stream } } }",
      { id: sceneId() }
    );
    const scene = data.findScene || {};
    const media = {
      duration: Math.max(0, ...(scene.files || []).map((f) => f.duration || 0)),
      stream: (scene.paths || {}).stream || null,
      cues: [],
      title: scene.title || "",
      file: (((scene.files || [])[0] || {}).path || "").split(/[\\/]/).pop(),
    };
    // Stash's seek bar thumbnails: a VTT file naming, per stretch of time,
    // a part of one big sprite image.
    const vtt = (scene.paths || {}).vtt;
    if (vtt) {
      try {
        const text = await (await fetch(vtt, { credentials: "include" })).text();
        const base = new URL(vtt, window.location.href);
        const time = (t) => t.split(":").reduce((acc, p) => acc * 60 + parseFloat(p), 0);
        text.split(/\r?\n\r?\n/).forEach((block) => {
          const m = block.match(/([\d:.]+)\s*-->\s*([\d:.]+)\s*\n\s*(\S+?)#xywh=(\d+),(\d+),(\d+),(\d+)/);
          if (m) {
            media.cues.push({ start: time(m[1]), end: time(m[2]), url: new URL(m[3], base).href,
              x: +m[4], y: +m[5], w: +m[6], h: +m[7] });
          }
        });
      } catch (e) {
        // no thumbnails then — the video itself is the fallback
      }
    }
    return media;
  }

  function review(dialog, result, defaultPrimary, checkAudio) {
    const existing = result.existing || [];
    const existingAt = (t) => existing.find((e) => Math.abs(e.seconds - t) < 1) || null;
    const exists = (t) => !!existingAt(t);
    const pieces = result.pieces || null; // titles placed at the pauses: every title, in order
    let stripTitles = true;
    const skips = []; // parts marked as not music, while placing titles at the pauses

    const makeRow = (m, piece) => ({
      title_full: m.title,
      title_stripped: m.title_stripped || m.title,
      title: m.title,
      seconds: m.seconds,
      end_seconds: m.end_seconds,
      primary_tag: m.primary_tag || "",
      tags: [...(m.tags || [])],
      pick: !exists(m.seconds),
      exists: exists(m.seconds),
      existing: existingAt(m.seconds), // ticked: this marker is updated instead
      piece: piece == null ? null : piece,
      notMusic: false,
      edited: false,
    });
    // With pieces, a row's texts live in its piece, so they survive placing again.
    if (pieces) pieces.forEach((p) => { p.edited = false; p.title_full = p.title; p.primary_tag = p.primary_tag || ""; });
    let rows = result.markers.map((m, i) => makeRow(m, pieces ? i : null));
    const textOf = (r) => (r.piece != null ? pieces[r.piece] : r);
    const applyStrip = () => rows.forEach((r) => {
      const t = textOf(r);
      if (!t.edited) t.title = stripTitles ? (t.title_stripped || t.title_full) : t.title_full;
    });

    const offset = el("input", { type: "number", step: "0.1", value: "0", className: "form-control form-control-sm d-inline-block", style: { width: "7em" } });
    const primaryAll = el("input", { type: "text", value: defaultPrimary, className: "form-control form-control-sm d-inline-block", style: { width: "14em" } });
    const stripBox = el("input", { type: "checkbox", checked: true, onchange: (e) => { stripTitles = e.target.checked; applyStrip(); render(); } });
    const tbody = el("tbody");
    const shifted = (s) => (s == null ? null : Math.max(0, s + (parseFloat(offset.value) || 0)));

    // null: not checked (yet); { loading } / { error }; or the pauses (see pauses.check)
    let audio = checkAudio || pieces ? { loading: true } : null;
    let media = null; // length and thumbnails, for the timeline
    const audioBar = el("div", { className: "small mb-2" });
    const notice = el("div", { className: "small mb-2 text-warning" });

    const endOf = (r, i) => {
      if (r.end_seconds != null) return r.end_seconds;
      const next = rows.slice(i + 1).find((x) => x.seconds > r.seconds);
      return next ? next.seconds : (media && media.duration) || r.seconds;
    };

    // -- not music --------------------------------------------------------------
    const markNotMusic = (r) => {
      if (r.piece != null && pieces) {
        if (!audio || audio.loading || audio.error) {
          notice.textContent = "The audio check hasn't finished yet — the titles can be placed again once it has.";
          return;
        }
        skips.push([r.seconds, endOf(r, rows.indexOf(r))]);
        replace();
      } else {
        r.notMusic = true;
        r.pick = false;
        render();
      }
    };
    const undoNotMusic = (r) => {
      if (r.piece == null && pieces && r.skip) {
        skips.splice(skips.indexOf(r.skip), 1);
        replace();
      } else {
        r.notMusic = false;
        r.pick = !r.exists;
        render();
      }
    };
    // Titles placed at the pauses: place them again around the not-music parts.
    const replace = () => {
      const picks = new Map(rows.filter((r) => r.piece != null).map((r) => [r.piece, r.pick]));
      const placed = placePieces(pieces.length, audio, skips);
      rows = placed.rows.map((p) => {
        if (p.notMusic) {
          const skip = skips.find(([s, e]) => Math.abs(s - p.seconds) < 3 || (p.seconds <= s && e <= p.end_seconds)) || null;
          return { ...makeRow({ title: "not music", seconds: p.seconds, end_seconds: p.end_seconds }), notMusic: true, pick: false, skip };
        }
        const row = makeRow({ seconds: p.seconds, end_seconds: p.end_seconds, title: "" }, p.piece);
        if (picks.has(p.piece)) row.pick = picks.get(p.piece);
        return row;
      });
      notice.textContent = placed.missing > 0
        ? `${placed.missing} title${placed.missing === 1 ? "" : "s"} got no piece: ${pieces.slice(pieces.length - placed.missing).map((p) => p.title).join("; ")} — too few pauses left.`
        : "";
      applyStrip();
      render();
    };

    // -- the audio check (see above) -----------------------------------------------
    const audioCell = (r) => {
      if (r.notMusic || !audio || audio.loading || audio.error) return audio && audio.loading && !r.notMusic ? "…" : "";
      const d = nearest(resumePoints(audio), shifted(r.seconds));
      if (d == null) return "";
      if (Math.abs(d) <= AT_PAUSE) return el("span", { className: "text-success", title: "Starts where the music starts again", textContent: "✓ at a pause" });
      if (Math.abs(d) <= NEAR_PAUSE) {
        const amount = `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} s`;
        return el("span", { className: "text-warning", style: { whiteSpace: "nowrap" } },
          `pause ${amount} `,
          el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: `move ${amount}`,
            title: `Move this marker by ${amount} — start and end — so it starts at the pause`,
            onclick: () => { snap(r, d); render(); } }));
      }
      return el("span", { className: "text-muted", textContent: "no pause near" });
    };
    // Move a marker by the amount suggested: start and end, so it keeps
    // its length.
    const snap = (r, d) => {
      r.seconds += d;
      if (r.end_seconds != null) r.end_seconds += d;
    };
    const renderAudioBar = () => {
      if (!checkAudio || !audio) return audioBar.replaceChildren();
      if (audio.loading) return audioBar.replaceChildren(el("span", { className: "text-muted", textContent: "Checking the pauses in the audio…" }));
      if (audio.error) return audioBar.replaceChildren(el("span", { className: "text-muted", textContent: `Couldn't check the audio: ${audio.error}` }));
      const music = rows.filter((r) => !r.notMusic);
      const points = resumePoints(audio);
      const at = music.filter((r) => Math.abs(nearest(points, shifted(r.seconds))) <= AT_PAUSE).length;
      const near = music.filter((r) => { const d = Math.abs(nearest(points, shifted(r.seconds))); return d > AT_PAUSE && d <= NEAR_PAUSE; });
      const parts = [el("span", { textContent:
        `${at} of ${music.length} marker${music.length === 1 ? "" : "s"} start at a pause in the audio (${audio.pauses.length} pause${audio.pauses.length === 1 ? "" : "s"} found). ` })];
      const current = parseFloat(offset.value) || 0;
      const best = bestShift(points, music.map((r) => r.seconds));
      if (best.count > at && Math.abs(best.shift - current) >= 0.5) {
        parts.push(el("span", { textContent: `${best.count} fit with all times shifted by ${best.shift > 0 ? "+" : ""}${best.shift.toFixed(1)} s — ` }),
          el("button", { type: "button", className: "btn btn-link btn-sm p-0 align-baseline", textContent: "shift",
            onclick: () => { offset.value = best.shift.toFixed(1); render(); } }), " ");
      }
      if (near.length) {
        parts.push(el("button", { type: "button", className: "btn btn-link btn-sm p-0 align-baseline",
          textContent: `move ${near.length} marker${near.length === 1 ? "" : "s"} by ${near.length === 1 ? "its" : "their"} suggested amount, onto the nearest pause`,
          onclick: () => { near.forEach((r) => snap(r, nearest(points, shifted(r.seconds)))); render(); } }));
      }
      audioBar.replaceChildren(...parts);
    };

    // -- the table as a timeline -----------------------------------------------------
    //
    // One row per marker, in time order, as tall as it lasts (a minimum
    // height keeps the fields usable; "Height" stretches the scale), and an
    // empty row for every gap between markers — a pause, applause, or music
    // without a marker. A strip on the left of every row shows the marker's
    // colour and the pauses found in the audio; hovering it shows that
    // moment of the video.
    const MIN_ROW = 38; // px: room for the fields
    const MIN_GAP = 24; // px: a gap row is a row of its own, with its label
    let zoom = 1;
    const zoomSelect = el("select", { className: "form-control form-control-sm d-inline-block", style: { width: "5em" },
      onchange: (e) => { zoom = parseFloat(e.target.value) || 1; render(); } },
      ...[1, 2, 4, 8].map((z) => el("option", { value: String(z), textContent: `${z}×` })));
    const preview = el("div", { className: "mac-preview" });
    const previewTime = el("div", { className: "mac-preview-time" });
    let previewVideo = null;
    const total = () => Math.max((media && media.duration) || 0,
      ...rows.map((r, i) => shifted(endOf(r, i)) || 0), audio && audio.music_end ? audio.music_end : 0, 1);
    // px per second: all rows together get about half a window more than
    // their minimum heights, times the zoom
    const scale = () => ((window.innerHeight * 0.5) / total()) * zoom;

    const showPreview = (event, bar, from, to) => {
      const rect = bar.getBoundingClientRect();
      const y = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
      const at = from + (rect.height ? (y / rect.height) * (to - from) : 0);
      bar.querySelector(".mac-hover-line").style.top = `${y}px`;
      bar.querySelector(".mac-hover-line").style.display = "block";
      previewTime.textContent = formatTime(at);
      const cue = media && media.cues.find((c) => at >= c.start && at < c.end);
      preview.replaceChildren();
      if (cue) {
        const k = 200 / cue.w;
        const frame = el("div", { style: {
          width: `${cue.w * k}px`, height: `${cue.h * k}px`,
          backgroundImage: `url("${cue.url}")`, backgroundRepeat: "no-repeat",
          backgroundPosition: `-${cue.x * k}px -${cue.y * k}px`,
        } });
        preview.append(frame);
        // the sprite is scaled with the frame: size it once it's known
        const img = new Image();
        img.onload = () => { frame.style.backgroundSize = `${img.width * k}px ${img.height * k}px`; };
        img.src = cue.url;
      } else if (media && media.stream) {
        if (!previewVideo) {
          previewVideo = el("video", { muted: true, preload: "metadata", src: media.stream, style: { width: "200px", display: "block" } });
        }
        clearTimeout(showPreview.seek);
        showPreview.seek = setTimeout(() => { try { previewVideo.currentTime = at; } catch (e) { /* not ready */ } }, 120);
        preview.append(previewVideo);
      }
      preview.append(previewTime);
      preview.style.display = "block";
      preview.style.left = `${rect.right + 10}px`;
      preview.style.top = `${Math.max(8, Math.min(window.innerHeight - 160, event.clientY - 60))}px`;
    };
    const hidePreview = (bar) => {
      bar.querySelector(".mac-hover-line").style.display = "none";
      preview.style.display = "none";
    };
    document.body.appendChild(preview);

    // The strip: the marker's colour, the pauses inside its time as lines.
    const strip = (kind, from, to, height) => {
      const bar = el("div", { className: `mac-bar mac-${kind}`, style: { height: `${height}px` } });
      if (audio && audio.pauses && to > from) {
        audio.pauses.forEach(([a, b]) => {
          if (b <= from || a >= to) return;
          bar.append(el("div", { className: "mac-pause", style: {
            top: `${((Math.max(a, from) - from) / (to - from)) * 100}%`,
            height: `max(1px, ${((Math.min(b, to) - Math.max(a, from)) / (to - from)) * 100}%)` } }));
        });
      }
      bar.append(el("div", { className: "mac-hover-line" }));
      bar.addEventListener("mousemove", (e) => showPreview(e, bar, from, to));
      bar.addEventListener("mouseleave", () => hidePreview(bar));
      return bar;
    };

    const columns = 7 + (checkAudio ? 1 : 0);
    // A gap between markers: a pause (light blue) or a stretch with music
    // but without a marker (amber) — a row of its own, always labelled.
    // How much of a stretch is quiet in the audio (0–1), or null before the
    // audio check is done.
    const quietShare = (from, to) => {
      if (!audio || !audio.pauses || to <= from) return null;
      const quiet = audio.pauses.reduce((sum, [a, b]) => sum + Math.max(0, Math.min(b, to) - Math.max(a, from)), 0);
      return quiet / (to - from);
    };
    const gapRow = (from, to, k) => {
      const height = Math.max(MIN_GAP, (to - from) * k);
      // a pause: mostly quiet in the audio, however long (applause can
      // last); without the audio check: up to 20 s
      const share = quietShare(from, to);
      const long = share == null ? to - from > 20 : share < 0.6 && to - from > 20;
      const label = long
        ? `${formatTime(to - from)} without a marker · ${formatTime(from)} – ${formatTime(to)}`
        : `⏸ pause ${formatTime(to - from)} · ${formatTime(from)} – ${formatTime(to)}`;
      return el("tr", { className: `mac-gap ${long ? "mac-gap-long" : "mac-gap-pause"}`, style: { height: `${height}px` } },
        el("td", { className: "mac-strip-cell" }, strip(long ? "gap-long" : "gap-pause", from, to, height)),
        el("td", { colSpan: columns - 1, className: "mac-gap-label", textContent: label }));
    };

    // -- the table ----------------------------------------------------------------------
    const render = () => {
      renderAudioBar();
      const k = scale();
      const order = rows.map((r, i) => ({ r, i, s: shifted(r.seconds), e: Math.max(shifted(r.seconds), shifted(endOf(r, i))) }))
        .sort((x, y) => x.s - y.s);
      const out = [];
      let cursor = 0;
      order.forEach(({ r, s, e }) => {
        if (s - cursor > 1) out.push(gapRow(cursor, s, k));
        out.push(markerRow(r, s, e, Math.max(MIN_ROW, (e - s) * k)));
        cursor = Math.max(cursor, e);
      });
      const end = total();
      if (end - cursor > 1) out.push(gapRow(cursor, end, k));
      tbody.replaceChildren(...out);
    };

    const markerRow = (r, s, e, height) => {
      const t = textOf(r);
      const timeText = `${formatTime(s)}${r.end_seconds != null || e > s ? ` – ${formatTime(e)}` : ""}`;
      const kind = r.notMusic ? "not-music" : r.exists ? "exists" : r.pick ? "picked" : "unpicked";
      const first = el("td", { className: "mac-strip-cell" }, strip(kind, s, e, height));
      if (r.notMusic) {
        return el("tr", { className: "mac-row-not-music", style: { height: `${height}px` } },
          first,
          el("td", {}),
          el("td", { style: { whiteSpace: "nowrap" } }, timeText),
          el("td", { colSpan: 3, className: "text-muted" },
            el("em", { textContent: r.piece == null && !pieces ? `not music — ${t.title || ""}` : "not music" })),
          checkAudio ? el("td", {}) : null,
          el("td", {}, el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: "undo",
            onclick: () => undoNotMusic(r) })));
      }
      const check = el("input", { type: "checkbox", checked: r.pick, onchange: (ev) => { r.pick = ev.target.checked; render(); } });
      const title = el("input", { type: "text", value: t.title, className: "form-control form-control-sm",
        oninput: (ev) => { t.title = ev.target.value; t.edited = true; } });
      const primary = el("input", { type: "text", value: t.primary_tag, placeholder: primaryAll.value, className: "form-control form-control-sm",
        oninput: (ev) => { t.primary_tag = ev.target.value; } });
      const tags = el("input", { type: "text", value: t.tags.join(", "), placeholder: "Tag, Tag …", className: "form-control form-control-sm",
        oninput: (ev) => { t.tags = ev.target.value.split(",").map((x) => x.trim()).filter(Boolean); } });
      return el("tr", { style: { height: `${height}px`, ...(r.exists && !r.pick ? { opacity: 0.6 } : {}) } },
        first,
        el("td", {}, check),
        el("td", { style: { whiteSpace: "nowrap" } }, timeText,
          el("div", { className: "small text-muted", textContent: formatTime(e - s) }),
          r.exists ? el("div", { className: "small text-warning",
            textContent: r.pick ? "updates the marker that's here" : "already a marker here — tick to update it" }) : null),
        el("td", {}, title),
        el("td", {}, primary),
        el("td", {}, tags),
        checkAudio ? el("td", { className: "small" }, audioCell(r)) : null,
        el("td", {}, el("button", { type: "button", className: "btn btn-link btn-sm p-0", style: { whiteSpace: "nowrap" },
          textContent: "not music", title: pieces
            ? "Applause, a speech … — not a piece: the titles after it move on to the next pieces"
            : "Applause, a speech … — not a piece: no marker for it",
          onclick: () => markNotMusic(r) })));
    };
    offset.addEventListener("input", render);
    primaryAll.addEventListener("input", render);

    const toggleAll = el("input", { type: "checkbox", checked: rows.every((r) => r.pick), title: "All / none",
      onchange: (e) => { rows.forEach((r) => { if (!r.notMusic) r.pick = e.target.checked; }); render(); } });

    if (!document.getElementById("mac-style")) {
      const style = el("style", { id: "mac-style" });
      style.textContent = [
        ".mac-table td { vertical-align: top; }",
        ".mac-table td.mac-strip-cell { width: 24px; padding: 0 6px 0 0 !important; }",
        ".mac-bar { position: relative; width: 18px; cursor: crosshair; border-radius: 2px; }",
        ".mac-picked { background: #3b82f6; } .mac-unpicked { background: #6b7280; } .mac-exists { background: #f59e0b; }",
        ".mac-not-music { background: repeating-linear-gradient(45deg, #6b7280 0 4px, transparent 4px 8px); }",
        ".mac-gap td { padding-top: 0 !important; padding-bottom: 0 !important; }",
        ".mac-gap-pause { background: rgba(56,189,248,.14); }",
        ".mac-gap-long { background: rgba(245,158,11,.12); }",
        ".mac-bar.mac-gap-pause { background: #38bdf8; }",
        ".mac-bar.mac-gap-long { background: repeating-linear-gradient(0deg, #f59e0b 0 3px, transparent 3px 7px); }",
        ".mac-gap-label { font-size: .78em; vertical-align: middle !important; white-space: nowrap; }",
        ".mac-gap-pause .mac-gap-label { color: #7dd3fc; }",
        ".mac-gap-long .mac-gap-label { color: #f59e0b; }",
        ".mac-pause { position: absolute; left: 0; right: 0; background: rgba(0,0,0,.6); }",
        ".mac-hover-line { display: none; position: absolute; left: -2px; right: -2px; height: 0; border-top: 2px solid #f43f5e; pointer-events: none; }",
        ".mac-preview { display: none; position: fixed; z-index: 3000; padding: 4px; background: #111; border-radius: 4px; box-shadow: 0 4px 16px rgba(0,0,0,.5); pointer-events: none; }",
        ".mac-preview-time { color: #fff; font-size: .8em; text-align: center; padding-top: 2px; }",
        ".mac-row-not-music { opacity: .6; }",
      ].join("\n");
      document.head.appendChild(style);
    }

    dialog.body.replaceChildren(
      result.notes ? el("div", { className: "alert alert-info py-2", textContent: result.notes }) : "",
      el("div", { className: "mb-2 d-flex flex-wrap align-items-center", style: { gap: "1em" } },
        el("label", { className: "mb-0" }, "Shift all times by ", offset, " s"),
        el("label", { className: "mb-0" }, "Primary tag (where none is given) ", primaryAll),
        el("label", { className: "mb-0" }, stripBox, " Take the tags' names out of the titles"),
        el("label", { className: "mb-0" }, "Height ", zoomSelect)),
      audioBar,
      notice,
      el("table", { className: "table table-sm mac-table" },
        el("thead", {}, el("tr", {},
          el("th", {}), el("th", {}, toggleAll), el("th", {}, "Time"), el("th", {}, "Title"), el("th", {}, "Primary tag"), el("th", {}, "Tags"),
          checkAudio ? el("th", {}, "Audio") : null, el("th", {}))),
        tbody),
      el("p", { className: "small text-muted", textContent:
        "Tags are matched by name or alias. A primary tag that doesn't exist yet is created; other tags that don't exist are left out." }));
    applyStrip();
    render();

    sceneMedia().then((m) => { media = m; render(); }).catch(() => {});
    if (checkAudio || pieces) {
      runOperation({ mode: "marker_pauses", scene_id: sceneId() })
        .then((data) => { audio = data; })
        .catch((err) => { audio = { error: String(err.message || err) }; })
        .then(render);
    }

    const create = el("button", { type: "button", className: "btn btn-primary", textContent: "Create markers",
      onclick: async () => {
        const picked = rows.filter((r) => r.pick && !r.notMusic).map((r) => {
          const t = textOf(r);
          return {
            title: t.title,
            tags: t.tags,
            seconds: shifted(r.seconds),
            end_seconds: shifted(r.end_seconds),
            primary_tag: (t.primary_tag || "").trim() || primaryAll.value.trim() || DEFAULT_PRIMARY,
            existing: r.exists ? r.existing : null,
          };
        });
        if (!picked.length) return;
        create.disabled = true;
        create.textContent = "Creating…";
        try {
          // Tags that don't exist yet (composers from the chapters, mostly):
          // ask what to do with them first.
          const resolved = await resolveNewTags(dialog, picked);
          if (!resolved.ok) {
            create.disabled = false;
            create.textContent = "Create markers";
            return;
          }
          const report = await createMarkers(picked);
          if (resolved.notes.length) report.text += "\n\n" + resolved.notes.join("\n");
          dialog.body.replaceChildren(el("div", { className: report.failed.length ? "alert alert-warning" : "alert alert-success",
            style: { whiteSpace: "pre-wrap" }, textContent: report.text }));
          create.remove();
          await refreshStash();
        } catch (err) {
          create.disabled = false;
          create.textContent = "Create markers";
          dialog.body.prepend(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
        }
      } });
    dialog.footer.prepend(create);
    // The markers as they'd be created, as text.
    let panel = null;
    const picked = () => rows.filter((r) => r.pick && !r.notMusic)
      .map((r, i) => {
        const t = textOf(r);
        return { seconds: shifted(r.seconds), end_seconds: shifted(endOf(r, rows.indexOf(r))), title: t.title, tags: t.tags,
          primary_tag: (t.primary_tag || "").trim() || primaryAll.value.trim() || DEFAULT_PRIMARY };
      })
      .sort((a, b) => a.seconds - b.seconds);
    const asText = el("button", { type: "button", className: "btn btn-secondary mr-auto", textContent: "Copy as text…",
      onclick: () => {
        if (!panel) {
          panel = exportPanel(picked, () => media || {});
          dialog.body.append(panel);
        } else {
          panel.refresh();
        }
        panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } });
    dialog.footer.prepend(asText);
    // The preview lives on the page: gone with the dialog.
    const watch = new MutationObserver(() => {
      if (!tbody.isConnected) { preview.remove(); watch.disconnect(); }
    });
    watch.observe(document.body, { childList: true });
  }

  // -- creating ----------------------------------------------------------------------------

  async function tagIndex() {
    const data = await gql("query { findTags(filter: { per_page: -1 }) { tags { id name aliases } } }");
    const index = new Map();
    data.findTags.tags.forEach((t) => {
      [t.name, ...(t.aliases || [])].forEach((n) => {
        const key = (n || "").trim().toLowerCase();
        if (key && !index.has(key)) index.set(key, String(t.id));
      });
    });
    return index;
  }

  // Before the markers are created: every tag of theirs that doesn't exist
  // yet gets a row — make it a composer (looked up on Wikidata with the
  // Classical Music scraper and created as a performer; Tag Improvements
  // then makes its tag), a plain tag, or leave it out. Every step is shown
  // as it happens; a tag that still doesn't exist afterwards is asked about
  // again — nothing is left out unless chosen. Resolves to { ok, notes }.
  async function resolveNewTags(dialog, markers) {
    const index = await tagIndex();
    const unknown = [...new Set(markers.flatMap((m) => m.tags || []))].filter((t) => t && !index.has(t.toLowerCase()));
    if (!unknown.length) return { ok: true, notes: [] };
    const scraperId = await performerScraperId().catch(() => null);
    const notes = [];

    const panel = el("div", { className: "alert alert-secondary" });
    const logList = el("ol", { className: "small mb-2 pl-3", style: { maxHeight: "12em", overflowY: "auto" } });
    const log = (text, kind) => {
      logList.append(el("li", { textContent: text, className: kind === "bad" ? "text-danger" : kind === "good" ? "text-success" : "" }));
      logList.scrollTop = logList.scrollHeight;
    };
    const buttons = el("div", { className: "mt-2" });
    dialog.body.prepend(panel);

    const makeRow = (name, preferComposer, previous) => {
      const select = el("select", { className: "form-control form-control-sm" },
        el("option", { value: "tag", textContent: "Create a plain tag" }),
        el("option", { value: "skip", textContent: "Leave it out" }));
      const state = el("span", { className: "small text-muted" });
      const composerBox = el("input", { type: "checkbox", checked: true });
      const composerLabel = el("label", { className: "small mb-0 ml-1 mr-2", style: { whiteSpace: "nowrap" } }, composerBox, " is a composer");
      const row = { name, select, state, found: [], composerBox, composerLabel };
      composerBox.addEventListener("change", () => describe(row));
      if (previous && previous.length) {
        // asked again: the composers found before, to try once more
        row.found = previous;
        select.prepend(...previous.map((p, i) => el("option", { value: `c${i}`,
          textContent: `Try again — performer from Wikidata: ${p.name}${p.disambiguation ? ` — ${p.disambiguation}` : ""}` })));
        select.value = "tag";
      } else if (scraperId && preferComposer) {
        select.prepend(el("option", { value: "", textContent: "Searching Wikidata …", disabled: true }));
        state.textContent = `Searching Wikidata for “${name}” …`;
        searchPerformers(scraperId, name).then((found) => {
          row.found = found;
          const waiting = select.querySelector('option[value=""]');
          if (waiting) waiting.remove();
          select.prepend(...found.map((p, i) => el("option", { value: `c${i}`,
            textContent: `Create performer from Wikidata: ${p.name}${p.disambiguation ? ` — ${p.disambiguation}` : ""}` })));
          const best = found.findIndex((p) => COMPOSER_WORDS.test(p.disambiguation || ""));
          select.value = best >= 0 ? `c${best}` : found.length ? "c0" : "tag";
          composerBox.checked = best >= 0;
          describe(row);
        }).catch((err) => {
          const waiting = select.querySelector('option[value=""]');
          if (waiting) waiting.remove();
          select.value = "tag";
          state.textContent = `Wikidata search failed: ${err.message || err}`;
        });
      } else {
        select.value = "tag";
      }
      select.addEventListener("change", () => describe(row));
      describe(row);
      return row;
    };
    const describe = (row) => {
      const v = row.select.value;
      row.composerLabel.style.display = v.startsWith("c") ? "" : "none";
      if (v.startsWith("c")) {
        const p = row.found[Number(v.slice(1))];
        row.state.textContent = row.composerBox.checked
          ? `→ performer “${p.name}” is created from Wikidata (portrait, dates, Wikipedia text), tagged Composer; its tag under Composers follows.`
          : `→ performer “${p.name}” is created from Wikidata (portrait, dates, Wikipedia text); its tag follows where its roles put it (e.g. Soloists).`;
      } else if (v === "tag") {
        row.state.textContent = `→ a tag “${row.name}” is created.`;
      } else if (v === "skip") {
        row.state.textContent = "→ the markers don't get this tag.";
      }
    };

    const ask = (rows, heading, intro) => new Promise((resolve) => {
      const go = el("button", { type: "button", className: "btn btn-primary btn-sm mr-2", textContent: "Continue" });
      const back = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Back to the markers" });
      go.onclick = () => resolve(true);
      back.onclick = () => resolve(false);
      buttons.replaceChildren(go, back);
      panel.replaceChildren(
        el("strong", { textContent: heading }),
        el("div", { className: "small mb-2", textContent: intro }),
        el("table", { className: "table table-sm mb-2" }, el("tbody", {}, ...rows.map((r) =>
          el("tr", {}, el("td", { style: { width: "28%" } }, el("strong", { textContent: r.name })),
            el("td", {}, el("div", { className: "d-flex align-items-center" }, r.select, r.composerLabel), r.state))))),
        logList, buttons);
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });

    const work = async (row) => {
      const v = row.select.value;
      if (v === "skip") {
        log(`“${row.name}”: left out, as chosen.`);
        notes.push(`Left out (chosen): ${row.name}`);
        return true;
      }
      if (v === "tag") {
        log(`Creating the tag “${row.name}” …`);
        await tagIdFor(row.name, true);
        log(`Tag “${row.name}” created.`, "good");
        notes.push(`Tag created: ${row.name}`);
        return true;
      }
      const picked = row.found[Number(v.slice(1))];
      const asComposer = row.composerBox.checked;
      log(`Getting ${picked.name} from Wikidata and creating the performer …`);
      const done = await createComposer(scraperId, picked, row.name, asComposer);
      log(done.existed
        ? `${done.name} was there already${asComposer ? ` — tagged ${done.marker}` : ""}.`
        : `Performer ${done.name} created${asComposer ? `, tagged ${done.marker}` : ""}.`, "good");
      log(`Waiting for its tag (Tag Improvements makes it) …`);
      let id = null;
      for (let i = 0; i < 10 && !id; i++) {
        await new Promise((res) => setTimeout(res, 1000));
        id = await tagIdFor(row.name, false);
      }
      if (!id) {
        log(asComposer ? `No tag yet — creating “${row.name}” under Composers myself.`
          : `No tag yet (no role of Tag Improvements fits) — creating the tag “${row.name}” myself.`);
        const parent = asComposer ? await tagIdFor("Composers", true).catch(() => null) : null;
        await gql("mutation($input: TagCreateInput!) { tagCreate(input: $input) { id } }",
          { input: { name: row.name, ...(parent ? { parent_ids: [parent] } : {}) } });
      }
      log(`Tag for “${row.name}” ready.`, "good");
      notes.push(`${asComposer ? "Composer" : "Performer"} created: ${done.name}${done.existed ? " (was there already)" : ""}`);
      return true;
    };

    let rows = unknown.map((name) => makeRow(name, true));
    let heading = `${unknown.length} tag${unknown.length === 1 ? "" : "s"} from the chapters don't exist yet`;
    let intro = scraperId
      ? "Names are looked up on Wikidata (Classical Music scraper) and created as performers — with portrait, dates and Wikipedia text — and Tag Improvements makes their tag: under Composers if ticked as a composer, else where their roles put them (a pianist, a soprano … under Soloists). Check the person picked for each, or make a plain tag, or leave it out."
      : "Make each a plain tag, or leave it out. (With the Classical Music performer scraper installed, composers could be looked up and created as performers.)";
    for (;;) {
      if (!(await ask(rows, heading, intro))) { panel.remove(); return { ok: false, notes }; }
      buttons.replaceChildren(el("span", { className: "small text-muted", textContent: "Working …" }));
      rows.forEach((r) => { r.select.disabled = true; r.composerBox.disabled = true; });
      for (const r of rows) {
        try {
          await work(r);
        } catch (err) {
          log(`“${r.name}”: ${err.message || err}`, "bad");
        }
      }
      // Anything still without a tag (and not left out on purpose)? Ask again.
      const fresh = await tagIndex();
      const missing = rows.filter((r) => r.select.value !== "skip" && !fresh.has(r.name.toLowerCase()));
      if (!missing.length) break;
      rows = missing.map((r) => makeRow(r.name, false, r.found));
      heading = `${missing.length} tag${missing.length === 1 ? "" : "s"} still missing`;
      intro = "These didn't work out (see the steps below). Try the composer again, make a plain tag, or leave them out.";
    }
    log("All tags ready — creating the markers.", "good");
    await new Promise((res) => setTimeout(res, 600));
    panel.remove();
    return { ok: true, notes };
  }

  async function createMarkers(markers) {
    const index = await tagIndex();
    const created = [];
    const updated = [];
    const failed = [];
    const skippedTags = new Set();
    const newTags = [];
    for (const m of markers) {
      try {
        if (m.existing && m.existing.id) {
          // A marker already here: new title, its tags plus the new ones;
          // primary tag and times stay as they are.
          const ids = new Set((m.existing.tags || []).map((t) => String(t.id)));
          m.tags.forEach((t) => {
            const id = index.get(t.toLowerCase());
            if (id) ids.add(id);
            else skippedTags.add(t);
          });
          const input = { id: m.existing.id, tag_ids: [...ids] };
          if (m.title) input.title = m.title;
          await gql("mutation($input: SceneMarkerUpdateInput!) { sceneMarkerUpdate(input: $input) { id } }", { input });
          updated.push(m);
          continue;
        }
        const key = m.primary_tag.toLowerCase();
        if (!index.has(key)) {
          const data = await gql("mutation($input: TagCreateInput!) { tagCreate(input: $input) { id } }", { input: { name: m.primary_tag } });
          index.set(key, String(data.tagCreate.id));
          newTags.push(m.primary_tag);
        }
        const tagIds = [];
        m.tags.forEach((t) => {
          const id = index.get(t.toLowerCase());
          if (id) tagIds.push(id);
          else skippedTags.add(t);
        });
        const input = {
          scene_id: sceneId(),
          title: m.title,
          seconds: m.seconds,
          primary_tag_id: index.get(key),
          tag_ids: tagIds,
        };
        if (m.end_seconds != null && m.end_seconds > m.seconds) input.end_seconds = m.end_seconds;
        await gql("mutation($input: SceneMarkerCreateInput!) { sceneMarkerCreate(input: $input) { id } }", { input });
        created.push(m);
      } catch (err) {
        failed.push(`${formatTime(m.seconds)} ${m.title}: ${err.message || err}`);
      }
    }
    const lines = [`${created.length} marker${created.length === 1 ? "" : "s"} created.`];
    if (updated.length) lines.push(`${updated.length} marker${updated.length === 1 ? "" : "s"} updated.`);
    if (newTags.length) lines.push(`New tag${newTags.length === 1 ? "" : "s"}: ${newTags.join(", ")}`);
    if (skippedTags.size) lines.push(`Left out (no such tag): ${Array.from(skippedTags).join(", ")}`);
    if (failed.length) lines.push("", "Failed:", ...failed);
    return { created, failed, text: lines.join("\n") };
  }

  // Stash's own page keeps the markers it loaded; ask it to load them again.
  async function refreshStash() {
    try {
      const service = window.PluginApi && window.PluginApi.utils && window.PluginApi.utils.StashService;
      const client = service && service.getClient && service.getClient();
      if (client && client.refetchQueries) {
        await client.refetchQueries({ include: "active" });
        return;
      }
    } catch (err) {
      console.warn("[Markers as Chapters] Couldn't refresh Stash's data; reloading the page:", err);
    }
    window.location.reload();
  }

  // -- offering chapters found ---------------------------------------------------------------
  //
  // A scene without markers is checked for chapters (see marker_available in
  // marker_scrapers.py: a chapter file — also a medici.tv JSON — next to the
  // video, the video's own chapters, ARTE / ORF ON through its URLs) when its
  // page opens and when its URLs change (e.g. after scraping it). If some are
  // found, a note at the bottom right offers to import them — also right
  // after the scene was saved (e.g. filled in by a scraper): the usual review
  // dialog (nothing is saved until "Create markers" there). "Not now"
  // doesn't ask again for that scene (in this browser).

  const OFFER_ID = "mac-chapter-offer";
  const DISMISSED_KEY = "markersAsChapters.offerDismissed";
  const checked = new Set(); // "<scene>|<urls>" already checked in this page

  function dismissed() {
    try { return new Set(JSON.parse(window.localStorage.getItem(DISMISSED_KEY) || "[]")); } catch (e) { return new Set(); }
  }
  function dismiss(id) {
    try {
      const set = dismissed();
      set.add(String(id));
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...set].slice(-500)));
    } catch (e) {
      // not remembered then
    }
  }

  function removeOffer() {
    const old = document.getElementById(OFFER_ID);
    if (old) old.remove();
  }

  function showOffer(scene, found) {
    removeOffer();
    const box = el("div", { id: OFFER_ID, className: "card p-3",
      style: { position: "fixed", right: "16px", bottom: "16px", zIndex: 1500, maxWidth: "380px",
        boxShadow: "0 6px 24px rgba(0,0,0,.5)" } },
      el("strong", { textContent: "Chapters found for this scene" }),
      el("div", { className: "small text-muted mb-2", textContent:
        "It has no markers yet. Import them as markers? You'll see them first — nothing is saved until you create them." }),
      ...found.map((f) => el("div", { className: "d-flex align-items-center mb-1", style: { gap: "8px" } },
        el("span", { className: "small", style: { flex: "1 1 auto" }, textContent: `${f.name} — ${f.count ? `${f.count} chapters` : f.label || "found"}` }),
        el("button", { type: "button", className: "btn btn-primary btn-sm", textContent: "Import…",
          onclick: () => { removeOffer(); scrape({ id: f.scraper, name: f.name }, null); } }))),
      el("div", { className: "text-right mt-2" },
        el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: "Not now",
          onclick: () => { dismiss(scene); removeOffer(); } })));
    document.body.appendChild(box);
  }

  async function checkForChapters() {
    const id = sceneId();
    if (!id) { removeOffer(); return; }
    if (dismissed().has(String(id))) return;
    let scene;
    try {
      scene = (await gql("query($id: ID!) { findScene(id: $id) { urls scene_markers { id } } }", { id })).findScene;
    } catch (e) {
      return;
    }
    if (!scene || (scene.scene_markers || []).length) { removeOffer(); return; }
    const key = `${id}|${(scene.urls || []).join(" ")}`;
    if (checked.has(key)) return;
    checked.add(key);
    try {
      const result = await runOperation({ mode: "marker_available", scene_id: id });
      if (sceneId() === id && (result.found || []).length) showOffer(id, result.found);
    } catch (e) {
      // nothing offered
    }
  }

  // After the scene is saved (e.g. filled in by a scraper — Sidecar reads the
  // same files next to the video), check again.
  document.addEventListener("click", (e) => {
    const button = e.target.closest ? e.target.closest("button") : null;
    if (!button || !/^(save|speichern|enregistrer)$/i.test(button.textContent.trim())) return;
    if (button.closest(".scene-markers-panel") || button.closest(`#${DIALOG_ID}`)) return; // marker forms, our dialog
    const id = sceneId();
    if (!id) return;
    [...checked].filter((k) => k.startsWith(`${id}|`)).forEach((k) => checked.delete(k));
    setTimeout(checkForChapters, 2500); // after Stash has saved
  }, true);

  // When a scene page opens (and after a save, above) — nothing in between,
  // so Stash isn't asked again and again while it's busy (generating
  // previews for new markers, say).
  // -- markers and the scene's files ----------------------------------------------------------
  //
  // A marker's time belongs to the file it was set on (marker_files.py keeps
  // which one). After merging scenes or changing the primary file, markers
  // set on another file of a different length are off: a note offers to
  // line them up with the primary file by comparing the two files' audio.

  const FILES_NOTE_ID = "mac-files-note";
  const FILES_DISMISSED_KEY = "markersAsChapters.filesNoteDismissed";

  function filesNoteDismissed(key) {
    try { return JSON.parse(window.localStorage.getItem(FILES_DISMISSED_KEY) || "[]").includes(key); } catch (e) { return false; }
  }
  function dismissFilesNote(key) {
    try {
      const list = JSON.parse(window.localStorage.getItem(FILES_DISMISSED_KEY) || "[]");
      list.push(key);
      window.localStorage.setItem(FILES_DISMISSED_KEY, JSON.stringify(list.slice(-300)));
    } catch (e) { /* not remembered then */ }
  }

  async function checkFiles() {
    const id = sceneId();
    const old = document.getElementById(FILES_NOTE_ID);
    if (old) old.remove();
    if (!id) return;
    let scene;
    try {
      scene = (await gql("query($id: ID!) { findScene(id: $id) { files { id } scene_markers { id } } }", { id })).findScene;
    } catch (e) { return; }
    if (!scene || (scene.files || []).length < 2 || !(scene.scene_markers || []).length) return;
    let info;
    try { info = await runOperation({ mode: "marker_files", scene_id: id }); } catch (e) { return; }
    if (!info || !info.off || sceneId() !== id) return;
    const key = `${id}|${info.files[0].id}|${info.off}`;
    if (filesNoteDismissed(key)) return;
    const primary = info.files[0];
    const box = el("div", { id: FILES_NOTE_ID, className: "card p-3",
      style: { position: "fixed", right: "16px", bottom: "16px", zIndex: 1500, maxWidth: "400px", boxShadow: "0 6px 24px rgba(0,0,0,.5)" } },
      el("strong", { textContent: "Markers from another file" }),
      el("div", { className: "small text-muted mb-2", textContent:
        `${info.off} marker${info.off === 1 ? " was" : "s were"} set on another file of this scene, of a different length — ` +
        `the primary file is ${primary.basename} (${formatTime(primary.duration)}). Their times may be off here.` }),
      el("div", { className: "d-flex", style: { gap: "8px" } },
        el("button", { type: "button", className: "btn btn-primary btn-sm", textContent: "Line them up…",
          onclick: () => { box.remove(); filesDialog(); } }),
        el("button", { type: "button", className: "btn btn-link btn-sm", textContent: "Not now",
          onclick: () => { dismissFilesNote(key); box.remove(); } })));
    document.body.appendChild(box);
  }

  async function filesDialog() {
    const note = document.getElementById(FILES_NOTE_ID);
    if (note) note.remove();
    const dialog = openDialog("Markers and the scene's files");
    dialog.body.append(el("p", { textContent: "Loading…" }));
    let info;
    try {
      info = await runOperation({ mode: "marker_files", scene_id: sceneId() });
    } catch (err) {
      dialog.body.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
      return;
    }
    const primary = info.files[0];
    const name = (fileId) => { const f = info.files.find((x) => String(x.id) === String(fileId)); return f ? f.basename : "?"; };
    const rows = info.files.map((f) => el("tr", {},
      el("td", { textContent: f.primary ? "primary" : "" }),
      el("td", { textContent: f.basename, style: { wordBreak: "break-all" } }),
      el("td", { textContent: formatTime(f.duration) }),
      el("td", { textContent: `${f.markers} marker${f.markers === 1 ? "" : "s"}` })));
    const others = info.files.filter((f) => !f.primary);
    const pick = el("select", { className: "form-control form-control-sm d-inline-block", style: { width: "auto", maxWidth: "100%" } },
      ...others.map((f) => el("option", { value: f.id, textContent: `${f.basename} (${formatTime(f.duration)}, ${f.markers} marker${f.markers === 1 ? "" : "s"})` })));
    const withUnknown = el("input", { type: "checkbox", checked: false });
    const result = el("div", { className: "mt-3" });
    const compare = el("button", { type: "button", className: "btn btn-primary btn-sm ml-2", textContent: "Compare the audio",
      title: "Quick: the two files' loudness, as a whole and around each marker. Needs the same sound in both.",
      onclick: () => lineUp(dialog, info, pick.value, withUnknown.checked, result, "audio") });
    const comparePicture = el("button", { type: "button", className: "btn btn-secondary btn-sm ml-2", textContent: "Compare the picture",
      title: "Every marker looked for in the primary file by its first seconds of picture — follows every cut, also with " +
        "other sound (another language, commentary). Slower: some seconds per marker.",
      onclick: () => lineUp(dialog, info, pick.value, withUnknown.checked, result, "picture") });
    if (others.length) {
      const best = others.slice().sort((a, b) => b.markers - a.markers)[0];
      pick.value = best.id;
    }
    dialog.body.replaceChildren(
      el("p", { className: "small text-muted", textContent:
        "A marker's time belongs to the file it was set on. When scenes are merged, Stash moves all their markers to one scene " +
        "with their times unchanged; when the primary file changes, the markers stay as they are. Markers set on a file of " +
        "another length (another cut, an intro more or less, PAL speed) can be lined up with the primary file here — " +
        "by comparing the two files' audio." }),
      el("table", { className: "table table-sm" }, el("tbody", {}, ...rows)),
      info.unknown ? el("p", { className: "small", textContent:
        `${info.unknown} marker${info.unknown === 1 ? "'s" : "s'"} file isn't known (set before Markers as Chapters remembered it — ` +
        "run the task \"Remember each marker's file\" once, before merging)." }) : "",
      others.length
        ? el("div", {}, "Markers set on ", pick, compare, comparePicture,
            info.unknown ? el("label", { className: "small ml-3" }, withUnknown, ` also the ${info.unknown} whose file isn't known`) : "")
        : el("p", { textContent: "The scene has one file: nothing to line up." }),
      result);
  }

  async function lineUp(dialog, info, fromFile, withUnknown, result, method) {
    const ids = withUnknown
      ? info.markers.filter((m) => String(m.file) === String(fromFile) || !m.file).map((m) => m.id)
      : [];
    result.replaceChildren(el("p", { textContent: method === "picture"
      ? "Looking for every marker's picture in the primary file … (some seconds per marker)"
      : "Comparing the audio of the two files … (reading a file's audio the first time takes a while)" }));
    let r;
    try {
      r = await runOperation({ mode: "marker_align", scene_id: sceneId(), from_file: fromFile, marker_ids: ids.join(","), method });
    } catch (err) {
      result.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
      return;
    }
    if (!r.markers.length) {
      result.replaceChildren(el("p", { textContent: "No markers known to be set on that file." }));
      return;
    }
    const pct = Math.round((r.speed - 1) * 1000) / 10;
    const same = r.likeness >= 0.6;
    const found = r.markers.filter((m) => !m.outside).length;
    const summary = method === "picture"
      ? `Found ${found} of ${r.markers.length} marker${r.markers.length === 1 ? "" : "s"} by their picture in the primary file` +
        (pct ? ` — it plays ${Math.abs(pct)} % ${pct > 0 ? "slower" : "faster"} (PAL / film speed)` : "") +
        ". Each one was looked for itself, so a shift that changes in between (a cut) is followed. " +
        "Those not found are left unticked."
      : same
      ? `The same recording (alike: ${Math.round(r.likeness * 100)} %): ${r.from.basename} is ` +
        (r.offset === 0 ? "in step with the primary file"
          : `in step with the primary file, but everything comes ${Math.abs(r.offset)} s ${r.offset < 0 ? "earlier" : "later"} there`) +
        (pct ? `, and plays ${Math.abs(pct)} % ${pct > 0 ? "faster" : "slower"} (PAL / film speed)` : "") +
        ". Each marker was compared in the two minutes around it, so cuts in between are followed."
      : `The two files don't sound alike (${Math.round(r.likeness * 100)} %) — perhaps not the same recording. Check before applying.`;
    // markers already on the primary file near where one would go: the same
    // piece twice after merging
    const onPrimary = info.markers.filter((m) => String(m.file) === String(info.files[0].id));
    const similar = (a, b) => {
      const w = (t) => new Set(String(t).toLowerCase().split(/\W+/).filter((x) => x.length > 2));
      const x = w(a), y = w(b);
      return !x.size || !y.size ? false : [...x].filter((v) => y.has(v)).length / Math.min(x.size, y.size) >= 0.6;
    };
    const rows = r.markers.map((m) => {
      const twin = onPrimary.find((p) => Math.abs(p.seconds - m.new_seconds) <= 5 && similar(p.title, m.title));
      const move = el("input", { type: "checkbox", checked: !twin && !m.outside && (method !== "picture" || m.likeness >= 0.6) });
      const drop = el("input", { type: "checkbox", checked: !!twin });
      const shift = Math.round((m.new_seconds - m.seconds) * 10) / 10;
      return { m, move, drop, twin, tr: el("tr", {},
        el("td", {}, move),
        el("td", { textContent: m.title || "(no title)" }),
        el("td", { textContent: formatTime(m.seconds) }),
        el("td", { textContent: `${formatTime(m.new_seconds)}${m.new_end_seconds != null ? ` – ${formatTime(m.new_end_seconds)}` : ""}` }),
        el("td", { textContent: `${shift > 0 ? "+" : ""}${shift} s`, style: { whiteSpace: "nowrap" } }),
        el("td", { className: "small" },
          m.outside ? (method === "picture" ? "its picture isn't in the primary file (cut away?) " : "not in the primary file (cut away?) ") : "",
          !m.outside && m.likeness < 0.6 ? (method === "picture" ? "picture hardly alike — check it " : "not alike around it — moved by the whole's offset ") : "",
          twin ? el("label", {}, drop, ` already a marker here (“${twin.title}”) — delete this one`) : "")) };
    });
    const apply = el("button", { type: "button", className: "btn btn-primary", textContent: "Apply",
      onclick: async () => {
        apply.disabled = true;
        const moved = [];
        let deleted = 0;
        const problems = [];
        for (const row of rows) {
          try {
            if (row.twin && row.drop.checked) {
              await gql("mutation($id: ID!) { sceneMarkerDestroy(id: $id) }", { id: row.m.id });
              deleted += 1;
            } else if (row.move.checked) {
              await gql("mutation($input: SceneMarkerUpdateInput!) { sceneMarkerUpdate(input: $input) { id } }",
                { input: { id: row.m.id, seconds: row.m.new_seconds, end_seconds: row.m.new_end_seconds } });
              moved.push(row.m);
            }
          } catch (err) {
            problems.push(`${row.m.title}: ${err.message || err}`);
          }
        }
        if (moved.length) {
          await runOperation({ mode: "marker_record", file_id: r.to.id, marker_ids: moved.map((m) => m.id).join(","),
            seconds: moved.map((m) => m.new_seconds).join(",") }).catch(() => null);
        }
        result.replaceChildren(el("div", { className: problems.length ? "alert alert-warning" : "alert alert-success", style: { whiteSpace: "pre-wrap" },
          textContent: `${moved.length} marker${moved.length === 1 ? "" : "s"} moved to the primary file, ${deleted} deleted.` +
            (problems.length ? `\nNot done:\n${problems.join("\n")}` : "") + "\nThe page reloads." }));
        setTimeout(() => window.location.reload(), 1500);
      } });
    result.replaceChildren(
      el("p", { className: same ? "" : "text-warning", textContent: summary }),
      el("table", { className: "table table-sm" },
        el("thead", {}, el("tr", {}, el("th", {}), el("th", { textContent: "Marker" }), el("th", { textContent: `On ${r.from.basename}` }),
          el("th", { textContent: "On the primary file" }), el("th", { textContent: "Shift" }), el("th", {}))),
        el("tbody", {}, ...rows.map((x) => x.tr))),
      apply);
  }

  let lastScene = null;
  setInterval(() => {
    const id = sceneId();
    if (id === lastScene) return;
    lastScene = id;
    removeOffer();
    if (id) setTimeout(checkForChapters, 1500);
    if (id) setTimeout(checkFiles, 2500);
  }, 2000);
})();
