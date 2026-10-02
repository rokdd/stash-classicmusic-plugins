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

  function gql(query, variables) {
    return fetch("/graphql", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }),
    })
      .then((r) => r.json())
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
    const item = (label, run) =>
      el("button", { type: "button", className: "dropdown-item", textContent: label, onclick: () => { closeMenu(); run(); } });
    const items = [];
    scrapers.filter((s) => s.fragment).forEach((s) => items.push(item(s.name, () => scrape(s, null))));
    scrapers.filter((s) => s.text).forEach((s) => items.push(item(`${s.name} — paste text or pick a file…`, () => textDialog(s))));
    const byUrl = scrapers.filter((s) => (s.urls || []).length);
    if (byUrl.length) {
      items.push(el("div", { className: "dropdown-divider" }));
      byUrl.forEach((s) => {
        urls.filter((u) => urlMatches(s, u)).forEach((u) => {
          let host = u;
          try { host = new URL(u).host.replace(/^www\./, ""); } catch (e) { /* keep it whole */ }
          items.push(item(`${s.name} — ${host}`, () => scrape(s, u)));
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
    menu.replaceChildren(...items);
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
      accept: ".txt,.cue,.md,.csv,.srt,.vtt,text/*",
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
      el("p", { className: "small text-muted", textContent: scraper.description ||
        "One marker per line with a time in it (e.g. a tracklist or a video description); the rest of the line is its title. " +
        "Times like 1:23, 1:02:03, [12:34], 3m20s; a range like 1:23 - 4:56 gives the end too. A CUE sheet works as well. " +
        "Titles only, without any times: they're taken as the pieces in order and placed at the pauses in the audio. " +
        "Pick a file or paste the text, check it, then scrape." }),
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
    dialog.body.append(el("p", { textContent: url ? `Scraping ${url} …` : "Scraping …" }));
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
      dialog.body.replaceChildren(el("div", { className: "alert alert-danger", style: { whiteSpace: "pre-wrap" }, textContent: String(err.message || err) }));
      return;
    }
    if (!result.markers.length) {
      dialog.body.replaceChildren(el("p", { textContent: result.notes || "No markers found." }));
      return;
    }
    review(dialog, result, (settings.scrapedMarkerTag || "").trim() || DEFAULT_PRIMARY, settings.skipPauseCheck !== true);
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

  function review(dialog, result, defaultPrimary, checkAudio) {
    const existing = result.existing || [];
    const exists = (m) => existing.some((e) => Math.abs(e.seconds - m.seconds) < 1);
    const rows = result.markers.map((m) => ({ ...m, pick: !exists(m), exists: exists(m) }));

    const offset = el("input", { type: "number", step: "0.1", value: "0", className: "form-control form-control-sm d-inline-block", style: { width: "7em" } });
    const primaryAll = el("input", { type: "text", value: defaultPrimary, className: "form-control form-control-sm d-inline-block", style: { width: "14em" } });
    const tbody = el("tbody");
    const shifted = (s) => (s == null ? null : Math.max(0, s + (parseFloat(offset.value) || 0)));

    // null: not checked (yet); { error }; or the pauses (see pauses.check)
    let audio = checkAudio ? { loading: true } : null;
    const audioBar = el("div", { className: "small mb-2" });

    const audioCell = (r) => {
      if (!audio || audio.loading || audio.error) return audio && audio.loading ? "…" : "";
      const d = nearest(resumePoints(audio), shifted(r.seconds));
      if (d == null) return "";
      if (Math.abs(d) <= AT_PAUSE) return el("span", { className: "text-success", title: "Starts where the music starts again", textContent: "✓ at a pause" });
      if (Math.abs(d) <= NEAR_PAUSE) {
        return el("span", { className: "text-warning", style: { whiteSpace: "nowrap" } },
          `pause ${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} s `,
          el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: "snap",
            title: "Move this marker onto the pause", onclick: () => { snap(r, d); render(); } }));
      }
      return el("span", { className: "text-muted", textContent: "no pause near" });
    };

    const snap = (r, d) => {
      r.seconds += d;
      if (r.end_seconds != null && r.end_seconds <= r.seconds) r.end_seconds = null;
    };

    const renderAudioBar = () => {
      if (!audio) return audioBar.replaceChildren();
      if (audio.loading) return audioBar.replaceChildren(el("span", { className: "text-muted", textContent: "Checking the pauses in the audio…" }));
      if (audio.error) return audioBar.replaceChildren(el("span", { className: "text-muted", textContent: `Couldn't check the audio: ${audio.error}` }));
      const points = resumePoints(audio);
      const at = rows.filter((r) => Math.abs(nearest(points, shifted(r.seconds))) <= AT_PAUSE).length;
      const near = rows.filter((r) => { const d = Math.abs(nearest(points, shifted(r.seconds))); return d > AT_PAUSE && d <= NEAR_PAUSE; });
      const parts = [el("span", { textContent:
        `${at} of ${rows.length} marker${rows.length === 1 ? "" : "s"} start at a pause in the audio (${audio.pauses.length} pause${audio.pauses.length === 1 ? "" : "s"} found). ` })];
      const current = parseFloat(offset.value) || 0;
      const best = bestShift(points, rows.map((r) => r.seconds));
      if (best.count > at && Math.abs(best.shift - current) >= 0.5) {
        parts.push(el("span", { textContent: `${best.count} fit with all times shifted by ${best.shift > 0 ? "+" : ""}${best.shift.toFixed(1)} s — ` }),
          el("button", { type: "button", className: "btn btn-link btn-sm p-0 align-baseline", textContent: "shift",
            onclick: () => { offset.value = best.shift.toFixed(1); render(); } }), " ");
      }
      if (near.length) {
        parts.push(el("button", { type: "button", className: "btn btn-link btn-sm p-0 align-baseline",
          textContent: `snap ${near.length} marker${near.length === 1 ? "" : "s"} onto the nearest pause`,
          onclick: () => { near.forEach((r) => snap(r, nearest(points, shifted(r.seconds)))); render(); } }));
      }
      audioBar.replaceChildren(...parts);
    };

    const render = () => {
      renderAudioBar();
      tbody.replaceChildren(...rows.map((r) => {
        const check = el("input", { type: "checkbox", checked: r.pick, onchange: (e) => { r.pick = e.target.checked; } });
        const title = el("input", { type: "text", value: r.title, className: "form-control form-control-sm", oninput: (e) => { r.title = e.target.value; } });
        const primary = el("input", { type: "text", value: r.primary_tag, placeholder: primaryAll.value, className: "form-control form-control-sm", oninput: (e) => { r.primary_tag = e.target.value; } });
        const tags = el("input", { type: "text", value: r.tags.join(", "), placeholder: "Tag, Tag …", className: "form-control form-control-sm",
          oninput: (e) => { r.tags = e.target.value.split(",").map((t) => t.trim()).filter(Boolean); } });
        return el("tr", { style: r.exists ? { opacity: 0.6 } : {} },
          el("td", {}, check),
          el("td", { style: { whiteSpace: "nowrap" } },
            `${formatTime(shifted(r.seconds))}${r.end_seconds != null ? ` – ${formatTime(shifted(r.end_seconds))}` : ""}`,
            r.exists ? el("div", { className: "small text-warning", textContent: "already a marker here" }) : null),
          el("td", {}, title),
          el("td", {}, primary),
          el("td", {}, tags),
          checkAudio ? el("td", { className: "small" }, audioCell(r)) : null);
      }));
    };
    offset.addEventListener("input", render);
    primaryAll.addEventListener("input", render);

    const toggleAll = el("input", { type: "checkbox", checked: rows.every((r) => r.pick), title: "All / none",
      onchange: (e) => { rows.forEach((r) => { r.pick = e.target.checked; }); render(); } });

    dialog.body.replaceChildren(
      result.notes ? el("div", { className: "alert alert-info py-2", textContent: result.notes }) : "",
      el("div", { className: "mb-2 d-flex flex-wrap align-items-center", style: { gap: "1em" } },
        el("label", { className: "mb-0" }, "Shift all times by ", offset, " s"),
        el("label", { className: "mb-0" }, "Primary tag (where none is given) ", primaryAll)),
      audioBar,
      el("table", { className: "table table-sm" },
        el("thead", {}, el("tr", {},
          el("th", {}, toggleAll), el("th", {}, "Time"), el("th", {}, "Title"), el("th", {}, "Primary tag"), el("th", {}, "Tags"),
          checkAudio ? el("th", {}, "Audio") : null)),
        tbody),
      el("p", { className: "small text-muted", textContent:
        "Tags are matched by name or alias. A primary tag that doesn't exist yet is created; other tags that don't exist are left out." }));
    render();
    if (checkAudio) {
      runOperation({ mode: "marker_pauses", scene_id: sceneId() })
        .then((data) => { audio = data; })
        .catch((err) => { audio = { error: String(err.message || err) }; })
        .then(render);
    }

    const create = el("button", { type: "button", className: "btn btn-primary", textContent: "Create markers",
      onclick: async () => {
        const picked = rows.filter((r) => r.pick).map((r) => ({
          ...r,
          seconds: shifted(r.seconds),
          end_seconds: shifted(r.end_seconds),
          primary_tag: (r.primary_tag || "").trim() || primaryAll.value.trim() || DEFAULT_PRIMARY,
        }));
        if (!picked.length) return;
        create.disabled = true;
        create.textContent = "Creating…";
        try {
          const report = await createMarkers(picked);
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

  async function createMarkers(markers) {
    const index = await tagIndex();
    const created = [];
    const failed = [];
    const skippedTags = new Set();
    const newTags = [];
    for (const m of markers) {
      try {
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
})();
