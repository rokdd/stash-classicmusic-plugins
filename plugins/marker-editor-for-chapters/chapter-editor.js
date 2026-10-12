// Marker Editor for Chapters — the scene's chapters (markers) in one table:
// in the Markers tab (in place of Stash's list; switch "Chapters | Stash's
// list"), or as a dialog. Add from every source (the scrapers of Markers as
// Chapters), combine duplicates, clean the titles and find the composers,
// extend to the next pause, see how often each chapter was played — and
// save it all at once.
//
// Uses Markers as Chapters (its own plugin, installed with this one) for
// the sources, the audio, the composers and the tags.
(function () {
  "use strict";

  function start(M) {
    const { PLUGIN_ID, OLD_PLUGIN_ID, DEFAULT_PRIMARY, AT_PAUSE, NEAR_PAUSE, gql, runOperation, sceneId, el, formatTime,
      parseTime, openDialog, findMarkersPanel, resumePoints, nearest, tagIndex, resolveNewTags, refreshStash } = M;

    // -- the chapter editor -------------------------------------------------------------------
    //
    // One panel for a scene's chapters: the markers in Stash, and whatever
    // the scrapers find added into the same table — a chapter at the same
    // time (±5 s) gets it as an alternative (use its title / times / tags),
    // the rest as new rows. Tools for all rows: clean the titles and find the
    // composers, extend each chapter to the next pause, move starts onto the
    // pauses, shift. Columns can be hidden (remembered). Save creates,
    // updates and deletes in one go.

    const EDITOR_COLS_KEY = "markersAsChapters.editorHiddenColumns";
    const EDITOR_COLUMNS = [["time", "Time"], ["title", "Title"], ["primary", "Primary tag"], ["tags", "Tags"],
      ["source", "Source"], ["audio", "Audio"], ["plays", "Played"]];

    // Inline (the Markers tab): the editor's body and buttons in `target`.
    function inlineFrame(target) {
      const body = el("div", {});
      const footer = el("div", { className: "d-flex justify-content-end mt-2", style: { gap: "8px" } });
      target.replaceChildren(body, footer);
      return { body, footer, close: () => {} };
    }

    async function chapterEditor(target) {
      const dialog = target ? inlineFrame(target) : openDialog("Chapter editor");
      dialog.body.append(el("p", { textContent: "Loading the scene's chapters …" }));
      let scene, scrapers, settings = {};
      try {
        const [data, list, conf] = await Promise.all([
          gql(`query($id: ID!) { findScene(id: $id) { id title urls files { duration }
            scene_markers { id title seconds end_seconds primary_tag { id name } tags { id name } } } }`, { id: sceneId() }),
          runOperation({ mode: "marker_scrapers_list" }),
          gql("query { configuration { plugins } }").catch(() => null)]);
        scene = data.findScene;
        scrapers = list || [];
        const plugins = (conf && conf.configuration.plugins) || {};
        settings = { ...(plugins[OLD_PLUGIN_ID] || {}), ...(plugins[PLUGIN_ID] || {}) };
      } catch (err) {
        dialog.body.replaceChildren(el("div", { className: "alert alert-danger", textContent: String(err.message || err) }));
        return;
      }
      const duration = Math.max(0, ...((scene.files || []).map((f) => f.duration || 0)));
      const defaultPrimary = (settings.scrapedMarkerTag || "").trim() || DEFAULT_PRIMARY;
      let counter = 0;
      const fromStash = (m) => {
        const row = { key: ++counter, id: m.id, seconds: m.seconds, end: m.end_seconds == null ? null : m.end_seconds,
          title: m.title || "", primary: (m.primary_tag && m.primary_tag.name) || "", tags: (m.tags || []).map((t) => t.name),
          source: "in Stash", alts: [], deleted: false };
        row.orig = JSON.stringify([row.seconds, row.end, row.title, row.primary, row.tags]);
        return row;
      };
      let rows = (scene.scene_markers || []).map(fromStash);
      let plays = {}; // marker id → {plays, seconds, last}
      runOperation({ mode: "chapter_stats", scene_id: sceneId() }).then((p) => { plays = p || {}; render(); }).catch(() => {});
      const playedText = (r) => {
        const p = r.id && plays[String(r.id)];
        if (!p) return r.id ? "not yet" : "";
        const ago = p.last ? Math.round((Date.now() - new Date(p.last).getTime()) / 86400000) : null;
        return `${p.plays}× · ${formatTime(p.seconds)}` + (ago == null ? "" : ` · ${ago === 0 ? "today" : ago === 1 ? "yesterday" : `${ago} days ago`}`);
      };
      let audio = null; // the pauses, once asked for
      const getAudio = async () => {
        if (!audio) audio = await runOperation({ mode: "marker_pauses", scene_id: sceneId() });
        return audio;
      };
      let hidden;
      try { hidden = new Set(JSON.parse(window.localStorage.getItem(EDITOR_COLS_KEY) || "[]")); } catch (e) { hidden = new Set(); }
      const status = el("div", { className: "small mb-2", style: { minHeight: "1.4em" } });
      const say = (text, kind) => { status.className = `small mb-2 ${kind === "bad" ? "text-danger" : kind === "good" ? "text-success" : "text-info"}`; status.textContent = text; };
      const live = () => rows.filter((r) => !r.deleted);
      const sorted = () => rows.slice().sort((a, b) => a.seconds - b.seconds);
      const endOf = (r) => {
        if (r.end != null) return r.end;
        const next = sorted().find((x) => !x.deleted && x.seconds > r.seconds);
        return next ? next.seconds : duration || r.seconds;
      };
      const changed = (r) => r.id && !r.deleted && JSON.stringify([r.seconds, r.end, r.title, r.primary, r.tags]) !== r.orig;

      // -- overview: the whole scene as a bar ----------------------------------------------------
      const overview = el("div", { style: { position: "relative", height: "22px", background: "rgba(255,255,255,.06)",
        borderRadius: "3px", margin: "4px 0 10px" } });
      const renderOverview = () => {
        const total = duration || Math.max(1, ...rows.map(endOf));
        const blocks = [];
        if (audio && audio.pauses) {
          audio.pauses.forEach(([a, b]) => blocks.push(el("div", { title: `pause ${formatTime(a)} – ${formatTime(b)}`, style: {
            position: "absolute", top: 0, bottom: 0, left: `${(a / total) * 100}%`, width: `max(1px, ${((b - a) / total) * 100}%)`,
            background: "rgba(56,189,248,.35)" } })));
        }
        sorted().forEach((r) => {
          const colour = r.deleted ? "#ef4444" : !r.id ? "#22c55e" : changed(r) ? "#f59e0b" : "#3b82f6";
          blocks.push(el("div", { title: `${formatTime(r.seconds)} ${r.title}`, style: {
            position: "absolute", top: "3px", bottom: "3px", left: `${(r.seconds / total) * 100}%`,
            width: `max(3px, calc(${((endOf(r) - r.seconds) / total) * 100}% - 2px))`, background: colour,
            opacity: r.deleted ? 0.4 : 0.85, borderRadius: "2px", cursor: "pointer" },
            onclick: () => { const tr = tbody.querySelector(`[data-key="${r.key}"]`); if (tr) { tr.scrollIntoView({ block: "center", behavior: "smooth" }); tr.style.outline = "2px solid #f59e0b"; setTimeout(() => { tr.style.outline = ""; }, 1500); } } }));
        });
        overview.replaceChildren(...blocks);
      };

      // -- the table ----------------------------------------------------------------------------------
      const tbody = el("tbody");
      const table = el("table", { className: "table table-sm mac-editor" });
      const grow = (box) => { box.style.height = "auto"; box.style.height = `${box.scrollHeight + 2}px`; };
      const timeInput = (value, onset, placeholder) => el("input", { type: "text", value: value == null ? "" : formatTime(value),
        placeholder, className: "form-control form-control-sm", style: { width: "6.5em" },
        onchange: (ev) => { const v = ev.target.value.trim(); onset(v === "" ? null : parseTime(v)); render(); } });
      const audioNote = (r) => {
        if (!audio || !audio.pauses) return "";
        const d = nearest(resumePoints(audio), r.seconds);
        if (d == null) return "";
        if (Math.abs(d) <= AT_PAUSE) return el("span", { className: "text-success", textContent: "✓ at a pause" });
        if (Math.abs(d) <= NEAR_PAUSE) {
          return el("button", { type: "button", className: "btn btn-link btn-sm p-0 text-warning", style: { whiteSpace: "nowrap" },
            textContent: `pause ${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} s`, title: "Move the start onto the pause",
            onclick: () => { r.seconds = Math.max(0, r.seconds + d); render(); } });
        }
        return el("span", { className: "text-muted", textContent: "no pause near" });
      };
      const row = (r) => {
        const cells = [];
        const td = (col, ...kids) => el("td", { className: `c-${col}` }, ...kids);
        const title = el("textarea", { rows: 1, value: r.title, className: "form-control form-control-sm mac-title",
          disabled: r.deleted, oninput: (ev) => { r.title = ev.target.value.replace(/\n/g, " "); grow(ev.target); renderOverview(); } });
        setTimeout(() => grow(title), 0);
        cells.push(td("time",
          el("div", { className: "d-flex", style: { gap: "4px" } },
            timeInput(r.seconds, (v) => { if (v != null) r.seconds = v; }, "start"),
            timeInput(r.end, (v) => { r.end = v; }, formatTime(endOf(r)))),
          el("div", { className: "small text-muted", textContent: `${formatTime(endOf(r) - r.seconds)} long` })));
        cells.push(td("title", title));
        cells.push(td("primary", el("input", { type: "text", value: r.primary, placeholder: defaultPrimary, disabled: r.deleted,
          className: "form-control form-control-sm", oninput: (ev) => { r.primary = ev.target.value; } })));
        cells.push(td("tags", el("input", { type: "text", value: r.tags.join(", "), placeholder: "Tag, Tag …", disabled: r.deleted,
          className: "form-control form-control-sm",
          oninput: (ev) => { r.tags = ev.target.value.split(",").map((x) => x.trim()).filter(Boolean); } })));
        const alts = r.alts.map((a, i) => el("div", { className: "small", style: { borderTop: "1px dotted rgba(255,255,255,.2)", paddingTop: "2px" } },
          el("span", { className: "text-muted", textContent: `${a.source}: ${formatTime(a.seconds)} ` }),
          el("span", { textContent: a.title || "—" }), " ",
          a.title ? el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: "title",
            onclick: () => { r.title = a.title; render(); } }) : "", " ",
          el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: "times",
            onclick: () => { r.seconds = a.seconds; if (a.end != null) r.end = a.end; render(); } }), " ",
          a.tags.length ? el("button", { type: "button", className: "btn btn-link btn-sm p-0", textContent: `+ tags`,
            title: a.tags.join(", "), onclick: () => { r.tags = [...new Set([...r.tags, ...a.tags])]; render(); } }) : "", " ",
          el("button", { type: "button", className: "btn btn-link btn-sm p-0 text-muted", textContent: "×", title: "Not this one",
            onclick: () => { r.alts.splice(i, 1); render(); } })));
        cells.push(td("source", el("div", { className: "small", textContent:
          r.deleted ? "deleted when saved" : !r.id ? `new — ${r.source}` : changed(r) ? "in Stash — changed" : "in Stash" }), ...alts));
        cells.push(td("audio", el("div", { className: "small" }, audioNote(r))));
        cells.push(td("plays", el("div", { className: "small text-muted", style: { whiteSpace: "nowrap" }, textContent: playedText(r) })));
        cells.push(el("td", {}, el("button", { type: "button", className: "btn btn-link btn-sm p-0", style: { whiteSpace: "nowrap" },
          textContent: r.deleted ? "restore" : "delete", onclick: () => {
            if (!r.id && !r.deleted) rows = rows.filter((x) => x !== r);
            else r.deleted = !r.deleted;
            render();
          } })));
        return el("tr", { "data-key": String(r.key), style: { opacity: r.deleted ? 0.45 : 1 } }, ...cells);
      };
      const render = () => {
        table.className = `table table-sm mac-editor ${[...hidden].map((c) => `hide-${c}`).join(" ")}`;
        tbody.replaceChildren(...sorted().map(row));
        renderOverview();
        const n = live().length;
        counts.textContent = `${n} chapter${n === 1 ? "" : "s"} · ${rows.filter((r) => !r.id && !r.deleted).length} new · `
          + `${rows.filter(changed).length} changed · ${rows.filter((r) => r.id && r.deleted).length} to delete`;
      };
      const counts = el("span", { className: "small text-muted" });

      // -- adding from a source ----------------------------------------------------------------------
      const merge = (found, source) => {
        let added = 0, combined = 0;
        found.forEach((m) => {
          const near = live().find((r) => Math.abs(r.seconds - m.seconds) <= 5);
          const item = { source, seconds: m.seconds, end: m.end_seconds == null ? null : m.end_seconds,
            title: m.title_stripped || m.title || "", tags: m.tags || [] };
          if (near) {
            if (!near.title && item.title) near.title = item.title;
            near.alts.push(item);
            combined += 1;
          } else {
            rows.push({ key: ++counter, id: null, seconds: item.seconds, end: item.end, title: item.title, primary: m.primary_tag || "",
              tags: [...item.tags], source, alts: [], deleted: false });
            added += 1;
          }
        });
        render();
        say(`${source}: ${added} new chapter${added === 1 ? "" : "s"}, ${combined} added as alternative${combined === 1 ? "" : "s"} to chapters at the same time.`, "good");
      };
      const sourceSelect = el("select", { className: "form-control form-control-sm d-inline-block", style: { width: "auto", maxWidth: "22em" } });
      const sources = [];
      scrapers.filter((s) => s.fragment && (!(s.urls || []).length || s.fragment_in_menu))
        .forEach((s) => sources.push({ label: s.name, scraper: s }));
      (scene.urls || []).forEach((u) => {
        const fits = scrapers.filter((s) => (s.urls || []).some((p) => p && !/^https?:?\/*$/i.test(p) && u.includes(p)));
        let host = u;
        try { host = new URL(u).host.replace(/^www\./, ""); } catch (e) { /* whole */ }
        fits.forEach((s) => sources.push({ label: `${s.name} — ${host}`, scraper: s, url: u }));
      });
      scrapers.filter((s) => s.text).forEach((s) => sources.push({ label: `${s.name} — paste text…`, scraper: s, text: true }));
      sources.forEach((src, i) => sourceSelect.append(el("option", { value: String(i), textContent: src.label })));
      const pasteBox = el("textarea", { className: "form-control form-control-sm mb-2", rows: 6, placeholder: "Paste the text here — times and titles, a CUE sheet, subtitles …",
        style: { display: "none", fontFamily: "monospace", fontSize: ".85em" } });
      sourceSelect.addEventListener("change", () => { pasteBox.style.display = sources[sourceSelect.value].text ? "" : "none"; });
      const addButton = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Add", onclick: async () => {
        const src = sources[sourceSelect.value];
        if (!src) return;
        if (src.text && !pasteBox.value.trim()) { pasteBox.style.display = ""; pasteBox.focus(); return; }
        addButton.disabled = true;
        say(`${src.label} …`);
        try {
          const result = await runOperation({ mode: "marker_scrape", scraper: src.scraper.id, scene_id: sceneId(),
            url: src.url || "", text: src.text ? pasteBox.value : "" });
          if (result.running) {
            say(`${src.scraper.name} runs as a Stash task (Settings → Tasks) — add it again here when it's done.`);
          } else if (!result.markers.length) {
            say(`${src.label}: nothing — ${result.notes || "no chapters found"}`, "bad");
          } else {
            merge(result.markers, src.scraper.name);
          }
        } catch (err) {
          say(`${src.label}: ${err.message || err}`, "bad");
        }
        addButton.disabled = false;
      } });

      // -- tools for all chapters ----------------------------------------------------------------------
      const tool = (label, title, run) => el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: label, title,
        onclick: async (ev) => { ev.target.disabled = true; try { await run(); } catch (err) { say(String(err.message || err), "bad"); } ev.target.disabled = false; } });
      const cleanTool = tool("Clean titles & composers", "Composers named in the titles become tags (under Composers), and the titles lose their names", async () => {
        say("Looking for composers in the titles …");
        const items = live();
        const out = await runOperation({ mode: "marker_suggest", markers: JSON.stringify(items.map((r) => ({ title: r.title, tags: r.tags }))) });
        let cleaned = 0, tagged = 0;
        items.forEach((r, i) => {
          const o = out[i] || {};
          if (o.title_stripped && o.title_stripped !== r.title) { r.title = o.title_stripped; cleaned += 1; }
          const more = (o.tags || []).filter((t) => !r.tags.includes(t));
          if (more.length) { r.tags = [...r.tags, ...more]; tagged += 1; }
        });
        render();
        say(`${tagged} chapter${tagged === 1 ? "" : "s"} got composer tags, ${cleaned} title${cleaned === 1 ? "" : "s"} cleaned.`, "good");
      });
      const extendTool = tool("Extend to the next pause", "Each chapter ends where the audio's next pause begins (not past the next chapter)", async () => {
        say("Reading the pauses in the audio …");
        const a = await getAudio();
        let n = 0;
        const list = sorted().filter((r) => !r.deleted);
        list.forEach((r, i) => {
          const next = list[i + 1] ? list[i + 1].seconds : duration || null;
          const from = Math.max(r.seconds + 10, r.end || 0);
          const pause = (a.pauses || []).find(([s]) => s >= from && (next == null || s < next));
          const end = pause ? pause[0] : next;
          if (end != null && end > r.seconds && (r.end == null || end > r.end + 0.5)) { r.end = Math.round(end * 10) / 10; n += 1; }
        });
        render();
        say(`${n} chapter${n === 1 ? "" : "s"} extended to the next pause.`, "good");
      });
      const snapTool = tool("Starts onto the pauses", "A start up to 20 s from where the music starts again is moved there", async () => {
        say("Reading the pauses in the audio …");
        const a = await getAudio();
        const points = resumePoints(a);
        let n = 0;
        live().forEach((r) => {
          const d = nearest(points, r.seconds);
          if (d != null && Math.abs(d) > 0.5 && Math.abs(d) <= NEAR_PAUSE) { r.seconds = Math.max(0, r.seconds + d); n += 1; }
        });
        render();
        say(`${n} start${n === 1 ? "" : "s"} moved onto a pause.`, "good");
      });
      const dupTool = tool("Combine duplicates", "Chapters less than 10 s apart: the fuller one stays, the other becomes its alternative (title, times, tags to take over)", async () => {
        const list = sorted().filter((r) => !r.deleted);
        const score = (r) => (r.id ? 1000 : 0) + (r.end != null ? 100 : 0) + r.title.length + r.tags.length;
        let n = 0;
        for (let i = 0; i + 1 < list.length; i += 1) {
          const a = list[i], b = list[i + 1];
          if (a.deleted || b.deleted || Math.abs(b.seconds - a.seconds) >= 10) continue;
          const [keep, other] = score(a) >= score(b) ? [a, b] : [b, a];
          keep.alts.push({ source: other.id ? "duplicate in Stash" : other.source, seconds: other.seconds, end: other.end,
            title: other.title, tags: [...other.tags] }, ...other.alts);
          if (other.id) other.deleted = true;
          else rows = rows.filter((x) => x !== other);
          list[i + 1] = keep; // a third close behind compares with the one kept
          n += 1;
        }
        render();
        say(n ? `${n} duplicate${n === 1 ? "" : "s"} combined — the other one is the kept chapter's alternative now${rows.some((r) => r.id && r.deleted) ? " (those in Stash are deleted when saving; restore to keep them)" : ""}.`
          : "No chapters less than 10 s apart.", n ? "good" : undefined);
      });
      const shiftBox = el("input", { type: "number", step: "0.5", value: "0", className: "form-control form-control-sm d-inline-block", style: { width: "5.5em" } });
      const shiftTool = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Shift all", onclick: () => {
        const d = parseFloat(shiftBox.value) || 0;
        if (!d) return;
        live().forEach((r) => { r.seconds = Math.max(0, r.seconds + d); if (r.end != null) r.end = Math.max(r.seconds, r.end + d); });
        shiftBox.value = "0";
        render();
      } });
      const atPlayer = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "+ chapter at the player",
        title: "A new chapter where the video is now", onclick: () => {
          const video = document.querySelector("video");
          const t = video ? Math.round(video.currentTime * 10) / 10 : 0;
          rows.push({ key: ++counter, id: null, seconds: t, end: null, title: "", primary: "", tags: [], source: "added by hand", alts: [], deleted: false });
          render();
        } });

      // -- columns ---------------------------------------------------------------------------------------
      const columnChips = el("span", { className: "small" }, "Columns: ",
        ...EDITOR_COLUMNS.map(([key, name]) => el("label", { className: "mb-0 mr-2", style: { whiteSpace: "nowrap", cursor: "pointer" } },
          el("input", { type: "checkbox", checked: !hidden.has(key), onchange: (ev) => {
            if (ev.target.checked) hidden.delete(key); else hidden.add(key);
            try { window.localStorage.setItem(EDITOR_COLS_KEY, JSON.stringify([...hidden])); } catch (e) { /* not remembered */ }
            render();
            if (key === "audio" && ev.target.checked && !audio) getAudio().then(render).catch(() => {});
          } }), ` ${name}`)));

      if (!document.getElementById("mac-editor-style")) {
        document.head.appendChild(el("style", { id: "mac-editor-style", textContent: [
          ".mac-editor td { vertical-align: top; }",
          ".mac-editor td.c-title { width: 100%; min-width: 12em; }",
          ".mac-editor td.c-primary input { min-width: 7em; } .mac-editor td.c-tags input { min-width: 10em; }",
          ".mac-editor td.c-source { min-width: 10em; max-width: 22em; }",
          ...EDITOR_COLUMNS.map(([key]) => `.mac-editor.hide-${key} .c-${key} { display: none; }`),
          "@media (max-width: 700px) { .mac-editor td, .mac-editor th { padding-left: 3px !important; padding-right: 3px !important; } }",
        ].join("\n") }));
      }
      table.append(el("thead", {}, el("tr", {}, ...EDITOR_COLUMNS.map(([key, name]) => el("th", { className: `c-${key}`, textContent: name })), el("th", {}))), tbody);
      dialog.body.replaceChildren(
        el("div", { className: "d-flex flex-wrap align-items-center mb-2", style: { gap: "6px" } },
          el("strong", { className: "small", textContent: "Add from" }), sourceSelect, addButton),
        pasteBox,
        el("div", { className: "d-flex flex-wrap align-items-center mb-2", style: { gap: "6px" } },
          cleanTool, dupTool, extendTool, snapTool, shiftBox, shiftTool, atPlayer),
        el("div", { className: "d-flex flex-wrap align-items-center", style: { gap: "10px" } }, columnChips, counts),
        overview, status, table);
      render();
      if (!hidden.has("audio")) getAudio().then(render).catch(() => {});

      // -- saving ------------------------------------------------------------------------------------------
      const save = el("button", { type: "button", className: "btn btn-primary", textContent: "Save", onclick: async () => {
        const toCreate = rows.filter((r) => !r.id && !r.deleted);
        const toUpdate = rows.filter(changed);
        const toDelete = rows.filter((r) => r.id && r.deleted);
        if (!toCreate.length && !toUpdate.length && !toDelete.length) { say("Nothing changed."); return; }
        save.disabled = true;
        try {
          const resolved = await resolveNewTags(dialog, [...toCreate, ...toUpdate].map((r) => ({ title: r.title, tags: r.tags })));
          if (!resolved.ok) { save.disabled = false; return; }
          const index = await tagIndex();
          const tagId = async (name) => {
            const key = name.trim().toLowerCase();
            if (!index.has(key)) {
              const data = await gql("mutation($input: TagCreateInput!) { tagCreate(input: $input) { id } }", { input: { name: name.trim() } });
              index.set(key, String(data.tagCreate.id));
            }
            return index.get(key);
          };
          const problems = [];
          const values = async (r) => {
            const v = { scene_id: sceneId(), title: r.title, seconds: Math.max(0, r.seconds),
              primary_tag_id: await tagId(r.primary.trim() || defaultPrimary),
              tag_ids: r.tags.map((t) => index.get(t.toLowerCase())).filter(Boolean) };
            if (r.end != null && r.end > r.seconds) v.end_seconds = r.end;
            return v;
          };
          let created = 0, updated = 0, deleted = 0;
          for (const r of toDelete) {
            try { await gql("mutation($id: ID!) { sceneMarkerDestroy(id: $id) }", { id: r.id }); deleted += 1; } catch (err) { problems.push(`${r.title}: ${err.message || err}`); }
          }
          for (const r of toUpdate) {
            try { await gql("mutation($i: SceneMarkerUpdateInput!) { sceneMarkerUpdate(input: $i) { id } }", { i: { id: r.id, ...(await values(r)) } }); updated += 1; } catch (err) { problems.push(`${r.title}: ${err.message || err}`); }
          }
          for (const r of toCreate) {
            try { await gql("mutation($i: SceneMarkerCreateInput!) { sceneMarkerCreate(input: $i) { id } }", { i: await values(r) }); created += 1; } catch (err) { problems.push(`${r.title}: ${err.message || err}`); }
          }
          dialog.body.replaceChildren(el("div", { className: problems.length ? "alert alert-warning" : "alert alert-success", style: { whiteSpace: "pre-wrap" },
            textContent: `${created} created, ${updated} updated, ${deleted} deleted.` + (resolved.notes.length ? `\n${resolved.notes.join("\n")}` : "")
              + (problems.length ? `\nNot done:\n${problems.join("\n")}` : "") }));
          save.remove();
          await refreshStash();
          if (target) setTimeout(() => chapterEditor(target), 1200); // the tab: the chapters as saved
        } catch (err) {
          save.disabled = false;
          say(String(err.message || err), "bad");
        }
      } });
      dialog.footer.prepend(save);
    }

    // -- the Markers tab as the chapter editor ---------------------------------
    //
    // "Chapters" (the default): Stash's marker list is hidden, the chapter
    // editor shown in its place (Marker Improvements' timeline stays). "Stash's
    // list": the tab as Stash has it. While Stash's own marker form is open
    // (Create Marker, editing one) the tab is Stash's; when it closes, the
    // editor loads the chapters again.
    const VIEW_KEY = "markersAsChapters.markersView";
    const inline = { scene: null, box: null, formOpen: false };

    function markersView() {
      try { return window.localStorage.getItem(VIEW_KEY) || "chapters"; } catch (e) { return "chapters"; }
    }

    function setMarkersView(view) {
      try { window.localStorage.setItem(VIEW_KEY, view); } catch (e) { /* this page only */ }
      applyView();
    }

    function applyView() {
      try {
        applyViewInner();
      } catch (err) {
        console.warn("[Markers as Chapters] chapter view:", err); // never into Stash's own page
      }
    }

    function applyViewInner() {
      const panel = findMarkersPanel();
      if (!panel || !sceneId()) return;
      // only while the Markers tab is shown (phones keep every tab in the
      // page, hidden): nothing is put into a tab nobody looks at
      if (!panel.offsetParent && panel.getClientRects().length === 0) return;
      const create = Array.from(panel.querySelectorAll("button.btn-primary")).find(
        (b) => !b.closest("form") && !b.closest("#marker-symbols-timeline") && !b.closest("#mac-inline-editor"));
      const bar = create ? create.parentElement : null;
      if (bar && !bar.querySelector("#mac-view-switch")) {
        const pick = (view, label) => el("button", { type: "button", className: "btn btn-sm btn-secondary", "data-view": view,
          textContent: label, onclick: () => setMarkersView(view) });
        bar.append(el("div", { id: "mac-view-switch", className: "btn-group ml-2" },
          pick("chapters", "Chapters"), pick("stash", "Stash's list")));
      }
      if (create && !create.dataset.macView) {
        create.dataset.macView = "1";
        create.addEventListener("click", () => { inline.formOpen = true; }, true); // Stash's form: shown as Stash has it
      }
      const form = !!panel.querySelector("form:not(#mac-inline-editor form)");
      const chapters = markersView() === "chapters" && !form;
      panel.querySelectorAll("#mac-view-switch button").forEach((b) => {
        b.className = `btn btn-sm ${(b.dataset.view === "chapters") === chapters ? "btn-primary" : "btn-secondary"}`;
      });
      // show / hide: everything in the tab but the path to the buttons, the
      // editor and Marker Improvements' timeline
      panel.querySelectorAll(".mac-hidden").forEach((n) => n.classList.remove("mac-hidden"));
      if (!chapters) {
        if (inline.box && inline.box.isConnected) inline.box.remove();
        if (form) inline.formOpen = true;
        return;
      }
      if (!inline.box || inline.scene !== sceneId() || inline.formOpen) {
        inline.box = inline.box && inline.scene === sceneId() ? inline.box : el("div", { id: "mac-inline-editor", className: "mt-2" });
        inline.scene = sceneId();
        inline.formOpen = false;
        chapterEditor(inline.box);
      }
      if (!inline.box.isConnected) {
        if (bar && bar.parentElement) bar.insertAdjacentElement("afterend", inline.box);
        else panel.prepend(inline.box);
      }
      const keep = new Set([inline.box, bar, panel.querySelector("#marker-symbols-timeline")].filter(Boolean));
      keep.forEach((node) => {
        // its ancestors up to the tab stay; their other children go
        let n = node;
        while (n && n !== panel && n.parentElement) {
          Array.from(n.parentElement.children).forEach((sib) => {
            if (sib !== n && ![...keep].some((k) => sib.contains(k) || k.contains(sib))) sib.classList.add("mac-hidden");
          });
          n = n.parentElement;
        }
      });
    }

    // -- play statistics per chapter ------------------------------------------------------------------
    //
    // While the scene's video plays, the seconds are counted for the chapter
    // they're in; a chapter counts as played once per visit after a minute of
    // it (or half of a shorter one). Sent every half minute and when the page
    // goes (chapter_plays.py keeps it).
    const tracker = { scene: null, chapters: [], loaded: 0, last: null, pending: {}, counted: new Set(), watched: {} };

    async function trackerChapters(id) {
      try {
        const data = await gql("query($id: ID!) { findScene(id: $id) { files { duration } scene_markers { id seconds end_seconds } } }", { id });
        const scene = data.findScene || {};
        const end = Math.max(0, ...((scene.files || []).map((f) => f.duration || 0)));
        const list = (scene.scene_markers || []).slice().sort((a, b) => a.seconds - b.seconds);
        tracker.chapters = list.map((m, i) => ({ id: String(m.id), from: m.seconds,
          to: m.end_seconds != null ? m.end_seconds : (list[i + 1] ? list[i + 1].seconds : end || Infinity) }));
      } catch (e) {
        tracker.chapters = [];
      }
      tracker.loaded = Date.now();
    }

    function flushPlays(leaving) {
      const plays = tracker.pending;
      if (!Object.keys(plays).length) return;
      tracker.pending = {};
      const body = JSON.stringify({ query: "mutation($plugin_id: ID!, $args: Map) { runPluginOperation(plugin_id: $plugin_id, args: $args) }",
        variables: { plugin_id: PLUGIN_ID, args: { mode: "chapter_play", plays: JSON.stringify(plays) } } });
      fetch("/graphql", { method: "POST", credentials: "include", keepalive: !!leaving,
        headers: { "Content-Type": "application/json" }, body }).catch(() => {});
    }

    setInterval(() => { try { trackPlay(); } catch (e) { /* never into Stash's page */ } }, 2000);
    function trackPlay() {
      const id = sceneId();
      if (id !== tracker.scene) {
        flushPlays();
        tracker.scene = id;
        tracker.chapters = [];
        tracker.counted = new Set();
        tracker.watched = {};
        tracker.last = null;
        if (id) trackerChapters(id);
        return;
      }
      if (!id) return;
      if (Date.now() - tracker.loaded > 60000) trackerChapters(id); // chapters changed meanwhile
      const video = document.querySelector("video");
      if (!video || video.paused || video.seeking) { tracker.last = null; return; }
      const t = video.currentTime;
      const step = tracker.last == null ? 0 : t - tracker.last;
      tracker.last = t;
      if (step <= 0 || step > 5) return; // a jump, not playing
      const chapter = tracker.chapters.find((c) => t >= c.from && t < c.to);
      if (!chapter) return;
      const p = tracker.pending[chapter.id] || (tracker.pending[chapter.id] = { seconds: 0, play: false });
      p.seconds += step;
      tracker.watched[chapter.id] = (tracker.watched[chapter.id] || 0) + step;
      const needed = Math.min(60, Math.max(5, (chapter.to - chapter.from) / 2));
      if (!tracker.counted.has(chapter.id) && tracker.watched[chapter.id] >= needed) {
        tracker.counted.add(chapter.id);
        p.play = true;
      }
    }
    setInterval(() => flushPlays(), 30000);
    window.addEventListener("pagehide", () => flushPlays(true));


    // the view in the Markers tab, kept up while Stash redraws its page
    if (!document.getElementById("mac-view-style")) {
      document.head.appendChild(el("style", { id: "mac-view-style", textContent: ".mac-hidden { display: none !important; }" }));
    }
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      setTimeout(() => { pending = false; if (sceneId()) applyView(); }, 200);
    }).observe(document.body, { childList: true, subtree: true });

    window.MarkerEditorForChapters = { open: () => chapterEditor() };
  }

  // Markers as Chapters' script may come after this one: wait for it
  let tries = 0;
  const wait = setInterval(() => {
    tries += 1;
    if (window.MarkersAsChapters) {
      clearInterval(wait);
      try { start(window.MarkersAsChapters); } catch (err) { console.warn("[Marker Editor for Chapters]", err); }
    } else if (tries > 100) {
      clearInterval(wait);
      console.warn("[Marker Editor for Chapters] needs the plugin Markers as Chapters — install or enable it.");
    }
  }, 100);
})();
