// Marker Improvements — marker scrapers
//
// Stash scrapes scenes, galleries, performers … but not markers. This
// adds marker scrapers that work like Stash's own (see marker_scrapers.py):
// a "Scrape markers" button next to "Create Marker" in a scene's Markers
// tab lists every marker scraper — one entry per scraper that scrapes the
// scene itself, and one per scene URL a URL scraper handles (plus "Other
// URL…"), like Stash's scrape menu. The markers found are shown in a
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

  const PLUGIN_ID = "markerImprovements";
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

  function findMarkersPanel() {
    return (
      document.querySelector('[id$="tabpane-scene-markers-panel"]') ||
      document.getElementById("scene-markers-panel")
    );
  }

  // Next to Stash's "Create Marker" button: the panel's primary button
  // outside any form.
  function placeButton() {
    if (!sceneId()) return;
    const panel = findMarkersPanel();
    if (!panel || panel.querySelector(`#${BUTTON_ID}`)) return;
    const create = Array.from(panel.querySelectorAll("button.btn-primary")).find((b) => !b.closest("form"));
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

  async function scrape(scraper, url) {
    const dialog = openDialog(`Scrape markers — ${scraper.name}`);
    dialog.body.append(el("p", { textContent: url ? `Scraping ${url} …` : "Scraping …" }));
    let result;
    let settings = {};
    try {
      const [res, conf] = await Promise.all([
        runOperation({ mode: "marker_scrape", scraper: scraper.id, scene_id: sceneId(), url: url || "" }),
        gql("query { configuration { plugins } }").catch(() => null),
      ]);
      result = res;
      settings = (conf && (conf.configuration.plugins || {})[PLUGIN_ID]) || {};
    } catch (err) {
      dialog.body.replaceChildren(el("div", { className: "alert alert-danger", style: { whiteSpace: "pre-wrap" }, textContent: String(err.message || err) }));
      return;
    }
    if (!result.markers.length) {
      dialog.body.replaceChildren(el("p", { textContent: "No markers found." }));
      return;
    }
    review(dialog, result, (settings.scrapedMarkerTag || "").trim() || DEFAULT_PRIMARY);
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

  function review(dialog, result, defaultPrimary) {
    const existing = result.existing || [];
    const exists = (m) => existing.some((e) => Math.abs(e.seconds - m.seconds) < 1);
    const rows = result.markers.map((m) => ({ ...m, pick: !exists(m), exists: exists(m) }));

    const offset = el("input", { type: "number", step: "0.1", value: "0", className: "form-control form-control-sm d-inline-block", style: { width: "7em" } });
    const primaryAll = el("input", { type: "text", value: defaultPrimary, className: "form-control form-control-sm d-inline-block", style: { width: "14em" } });
    const tbody = el("tbody");
    const shifted = (s) => (s == null ? null : Math.max(0, s + (parseFloat(offset.value) || 0)));

    const render = () => {
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
          el("td", {}, tags));
      }));
    };
    offset.addEventListener("input", render);
    primaryAll.addEventListener("input", render);

    const toggleAll = el("input", { type: "checkbox", checked: rows.every((r) => r.pick), title: "All / none",
      onchange: (e) => { rows.forEach((r) => { r.pick = e.target.checked; }); render(); } });

    dialog.body.replaceChildren(
      el("div", { className: "mb-2 d-flex flex-wrap align-items-center", style: { gap: "1em" } },
        el("label", { className: "mb-0" }, "Shift all times by ", offset, " s"),
        el("label", { className: "mb-0" }, "Primary tag (where none is given) ", primaryAll)),
      el("table", { className: "table table-sm" },
        el("thead", {}, el("tr", {},
          el("th", {}, toggleAll), el("th", {}, "Time"), el("th", {}, "Title"), el("th", {}, "Primary tag"), el("th", {}, "Tags"))),
        tbody),
      el("p", { className: "small text-muted", textContent:
        "Tags are matched by name or alias. A primary tag that doesn't exist yet is created; other tags that don't exist are left out." }));
    render();

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
      console.warn("[Marker Improvements] Couldn't refresh Stash's data; reloading the page:", err);
    }
    window.location.reload();
  }
})();
