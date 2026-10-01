// Scene Improvements — tools on Settings → Tools
//
// A page at /plugin/file-tools with three tabs:
//   - Torrent check: which videos in a folder of .torrent files are
//     already in the library (fuzzy file-name match, see torrent_check.py),
//     as a table with sizes, codec, resolution and the match's certainty.
//     Runs directly through Stash's runPluginOperation, so the table shows
//     as soon as it's done — no task queue.
//   - Download: downloads with yt-dlp into a library folder (see
//     ytdlp_downloader.py), as a Stash task.
//   - Task history: finished tasks (see task-history.js).
// They're shown on Stash's Settings → Tools page (see placeOnToolsPage);
// /plugin/file-tools still shows them as a page of their own.

(function () {
  "use strict";

  const api = window.PluginApi;
  if (!api || !api.React || !api.register || !api.register.route) return;
  const React = api.React;
  const h = React.createElement;
  const { useState, useEffect, useMemo } = React;
  const { Link } = api.libraries.ReactRouterDOM;

  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "advancedFileOperations";
  const ROUTE = "/plugin/file-tools";
  const REMEMBER_KEY = "advancedFileOperations.fileTools";

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

  function remembered() {
    try {
      return JSON.parse(localStorage.getItem(REMEMBER_KEY) || "{}");
    } catch (e) {
      return {};
    }
  }
  function remember(patch) {
    try {
      localStorage.setItem(REMEMBER_KEY, JSON.stringify({ ...remembered(), ...patch }));
    } catch (e) {
      // Not remembered this time.
    }
  }

  function formatSize(bytes) {
    if (!bytes) return "–";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let n = bytes;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i++;
    }
    return `${n.toFixed(i >= 3 ? 2 : 0)} ${units[i]}`;
  }

  // -- Torrent check ------------------------------------------------------------

  const STATUS = {
    in_library: { label: "In library", color: "#2e9e4f" },
    possible: { label: "Possible match", color: "#d39e00" },
    not_found: { label: "Not found", color: "#6c757d" },
  };

  function TorrentCheck() {
    const [folder, setFolder] = useState(remembered().torrentFolder || "");
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    const [running, setRunning] = useState(false);
    const [filter, setFilter] = useState("all");

    // `automatic`: the check that runs on opening the tab — it stays quiet
    // when no folder is set up yet, instead of showing an error.
    const run = async (automatic = false) => {
      setRunning(true);
      setError(null);
      remember({ torrentFolder: folder });
      try {
        const data = await gql(
          "mutation($plugin_id: ID!, $args: Map) { runPluginOperation(plugin_id: $plugin_id, args: $args) }",
          { plugin_id: PLUGIN_ID, args: { mode: "torrent_check", folder } }
        );
        setResult(data.runPluginOperation);
      } catch (err) {
        const message = err.message || String(err);
        if (!(automatic && /No torrent folder given/.test(message))) setError(message);
      } finally {
        setRunning(false);
      }
    };

    // Opening the tab checks right away, so the table is always current —
    // with the folder(s) last used here, or else the plugin setting's.
    useEffect(() => {
      run(true);
    }, []);

    // Deletes a torrent file (after asking), and drops its rows from the table.
    const deleteTorrent = async (row) => {
      const path = `${row.torrent_folder}/${row.torrent}`;
      if (!window.confirm(`Delete the torrent file?\n\n${path}\n\n(Only the .torrent file — no video is touched.)`)) return;
      try {
        await gql(
          "mutation($plugin_id: ID!, $args: Map) { runPluginOperation(plugin_id: $plugin_id, args: $args) }",
          { plugin_id: PLUGIN_ID, args: { mode: "torrent_check", folder: result.folder, delete: path } }
        );
        setResult((prev) => ({
          ...prev,
          rows: prev.rows.filter((r) => !(r.torrent === row.torrent && r.torrent_folder === row.torrent_folder)),
        }));
      } catch (err) {
        window.alert(`Couldn't delete it: ${err.message || err}`);
      }
    };

    const rows = useMemo(() => {
      if (!result) return [];
      return result.rows
        .filter((r) => filter === "all" || r.status === filter)
        .slice()
        .sort((a, b) => b.certainty - a.certainty);
    }, [result, filter]);

    const cell = { padding: "6px 8px", verticalAlign: "top", borderTop: "1px solid rgba(255,255,255,0.1)" };
    const muted = { opacity: 0.65, fontSize: "0.85em" };

    const table = result && h("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: "0.9em" } },
      h("thead", null, h("tr", null,
        ["Match", "Torrent / file", "Size", "Res. / codec (from name)", "Scene", "Scene size", "Scene res. / codec"]
          .map((t) => h("th", { key: t, style: { ...cell, textAlign: "left", borderTop: "none" } }, t)))),
      h("tbody", null, rows.map((r, i) => {
        const m = r.match;
        const st = STATUS[r.status];
        const showMatch = m && r.status !== "not_found";
        return h("tr", { key: i },
          h("td", { style: cell },
            h("span", { className: "badge", style: { background: st.color, color: "#fff" } }, `${r.certainty}%`),
            h("div", { style: muted }, st.label)),
          h("td", { style: { ...cell, wordBreak: "break-word" } },
            h("div", null, r.file),
            h("div", { style: muted }, r.torrent, r.torrent_folder ? ` — ${r.torrent_folder}` : ""),
            h("button", {
              type: "button", className: "btn btn-link btn-sm text-danger", style: { padding: 0 },
              title: "Delete this .torrent file", onClick: () => deleteTorrent(r),
            }, "Delete torrent")),
          h("td", { style: cell }, formatSize(r.size)),
          h("td", { style: cell }, [r.resolution_guess, r.codec_guess].filter(Boolean).join(" · ") || "–"),
          h("td", { style: { ...cell, wordBreak: "break-word" } },
            showMatch
              ? [h(Link, { key: "l", to: `/scenes/${m.scene_id}` }, m.scene_title || m.basename),
                h("div", { key: "f", style: muted }, m.basename)]
              : m
                ? h("span", { style: muted }, `closest: ${m.scene_title || m.basename}`)
                : "–"),
          h("td", { style: cell }, showMatch ? formatSize(m.size) : "–"),
          h("td", { style: cell }, showMatch ? [m.resolution, m.codec].filter(Boolean).join(" · ") || "–" : "–"));
      })));

    return h("div", null,
      h("p", { style: muted },
        "Reads every .torrent file in a folder on the server and looks for each video in your library " +
        "by its file name. Release tags like 1080p or x265 are ignored, numbers count (Symphony No. 5 ≠ No. 7), " +
        "and an identical file size counts as the same file. A torrent's resolution and codec can only be " +
        "guessed from its name."),
      h("div", { style: { display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "12px" } },
        h("input", {
          className: "form-control", style: { maxWidth: "460px" }, value: folder,
          placeholder: "Folder(s) with .torrent files, separated by ; (empty: the plugin setting)",
          onChange: (e) => setFolder(e.target.value),
          onKeyDown: (e) => { if (e.key === "Enter" && !running) run(); },
        }),
        h("button", { type: "button", className: "btn btn-primary", disabled: running, onClick: () => run() },
          running ? "Checking…" : "Run check"),
        result && h("select", {
          className: "form-control", style: { maxWidth: "220px" }, value: filter,
          onChange: (e) => setFilter(e.target.value),
        },
          h("option", { value: "all" }, `All (${result.videos})`),
          Object.keys(STATUS).map((s) => h("option", { key: s, value: s }, `${STATUS[s].label} (${result.counts[s]})`)))),
      error && h("div", { className: "text-danger", style: { marginBottom: "12px" } }, error),
      result && h("div", { style: { ...muted, marginBottom: "8px" } },
        `${result.torrents} torrent file(s) in ${result.folder}, ${result.videos} video(s), ` +
        `compared with ${result.library_files} library file(s).` +
        (result.skipped_samples ? ` ${result.skipped_samples} sample clip(s) skipped.` : "") +
        (result.unreadable.length ? ` Couldn't read: ${result.unreadable.map((u) => u.file).join(", ")}.` : "")),
      table);
  }

  // -- Download (yt-dlp) --------------------------------------------------------

  const QUALITIES = [
    { value: "best", label: "Best available" },
    { value: "2160", label: "Up to 4K (2160p)" },
    { value: "1080", label: "Up to 1080p" },
    { value: "720", label: "Up to 720p" },
  ];

  function Download() {
    const last = remembered();
    const [paths, setPaths] = useState(null);
    const [urls, setUrls] = useState("");
    const [dest, setDest] = useState(last.dest || "");
    const [subfolder, setSubfolder] = useState(last.subfolder || "");
    const [quality, setQuality] = useState(last.quality || "best");
    const [background, setBackground] = useState(false);
    const [message, setMessage] = useState(null);

    useEffect(() => {
      gql("query { configuration { general { stashes { path excludeVideo } } } }")
        .then((data) => {
          const list = (data.configuration.general.stashes || []).filter((s) => !s.excludeVideo).map((s) => s.path);
          setPaths(list);
          if (!list.includes(dest)) setDest(list[0] || "");
        })
        .catch((err) => setMessage({ error: true, text: `Couldn't read your library folders: ${err.message || err}` }));
    }, []);

    const start = async () => {
      const list = urls.split("\n").map((u) => u.trim()).filter(Boolean);
      if (!list.length) {
        setMessage({ error: true, text: "Paste at least one URL." });
        return;
      }
      remember({ dest, subfolder: subfolder.trim(), quality });
      const where = subfolder.trim() ? `${dest}/${subfolder.trim()}` : dest;
      try {
        await gql(
          "mutation($plugin_id: ID!, $description: String, $args_map: Map) { runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map) }",
          {
            plugin_id: PLUGIN_ID,
            description: `Download ${list.length} URL${list.length === 1 ? "" : "s"} to ${where}${background ? " (started in background)" : ""}`,
            args_map: {
              mode: "ytdlp_download", urls: list.join("\n"), dest, subfolder: subfolder.trim(), quality,
              background: background ? "true" : "false",
              task_description: `Download ${list.length} URL${list.length === 1 ? "" : "s"} to ${where}`,
            },
          }
        );
        setUrls("");
        setMessage({ error: false, text: "Queued ✓ — progress in Settings → Tasks." });
      } catch (err) {
        setMessage({ error: true, text: `Couldn't start the download: ${err.message || err}` });
      }
    };

    const label = (text, input, hint) => h("label", { style: { display: "flex", flexDirection: "column", gap: "4px", maxWidth: "560px" } },
      text, input, hint && h("span", { style: { opacity: 0.65, fontSize: "0.85em" } }, hint));

    if (paths && !paths.length) return h("p", null, "You have no library folders for videos yet (Settings → Library).");
    return h("div", { style: { display: "flex", flexDirection: "column", gap: "12px" } },
      label("Video or playlist URLs, one per line",
        h("textarea", { className: "form-control", rows: 4, value: urls, placeholder: "https://…", onChange: (e) => setUrls(e.target.value) })),
      label("Save into library folder",
        h("select", { className: "form-control", value: dest, onChange: (e) => setDest(e.target.value) },
          (paths || []).map((p) => h("option", { key: p, value: p }, p)))),
      label("Subfolder (optional)",
        h("input", { className: "form-control", value: subfolder, placeholder: "e.g. Concerts", onChange: (e) => setSubfolder(e.target.value) }),
        "Created if it doesn't exist yet."),
      label("Quality",
        h("select", { className: "form-control", value: quality, onChange: (e) => setQuality(e.target.value) },
          QUALITIES.map((q) => h("option", { key: q.value, value: q.value }, q.label)))),
      h("label", { style: { display: "flex", gap: "8px", alignItems: "flex-start" } },
        h("input", { type: "checkbox", checked: background, onChange: (e) => setBackground(e.target.checked), style: { marginTop: "4px" } }),
        "Run in the background — Stash's task queue stays free while it downloads; progress goes to a log file on the server."),
      h("div", null, h("button", { type: "button", className: "btn btn-primary", disabled: !paths, onClick: start }, "Download")),
      message && h("div", { className: message.error ? "text-danger" : "text-success" }, message.text));
  }

  // -- the page -------------------------------------------------------------------

  // The tools with their tabs. `embedded`: inside the Settings → Tools page
  // (see placeOnToolsPage), so without a page title and padding of its own.
  function FileToolsPage({ embedded } = {}) {
    // ?tab=… (older links to /plugin/file-tools) wins over the last tab used.
    const fromUrl = new URLSearchParams(window.location.search).get("tab");
    const [tab, setTab] = useState(fromUrl || remembered().tab || "torrents");
    useEffect(() => {
      if (fromUrl && fromUrl !== tab) setTab(fromUrl);
    }, [fromUrl]);
    const choose = (t) => {
      remember({ tab: t });
      setTab(t);
    };
    const tabButton = (value, text) => h("li", { className: "nav-item", key: value },
      h("a", {
        href: "#", className: `nav-link${tab === value ? " active" : ""}`,
        onClick: (e) => { e.preventDefault(); choose(value); },
      }, text));
    return h("div", embedded ? null : { className: "container-fluid", style: { padding: "16px 24px" } },
      !embedded && h("h2", null, "File Tools"),
      h("ul", { className: "nav nav-tabs", style: { marginBottom: "16px" } },
        tabButton("torrents", "Torrent check"),
        tabButton("download", "Download (yt-dlp)"),
        tabButton("history", "Task history")),
      tab === "torrents" ? h(TorrentCheck)
        : tab === "download" ? h(Download)
          // From task-history.js, loaded before this file.
          : window.AFOTaskHistory ? h(window.AFOTaskHistory.View) : h("p", null, "Task history isn't available."));
  }

  api.register.route(ROUTE, FileToolsPage);

  // -- on Settings → Tools ------------------------------------------------------------
  //
  // Everything lives on Stash's own Tools page: a "Scene Improvements"
  // section after Stash's own tool sections, built the same way (same kind
  // of section, heading and card), holding the tools with their tabs. The
  // Tools page isn't something plugins can extend, so the section is added
  // to the page; if a Stash version builds that page differently, it just
  // doesn't appear — the tools are still at /plugin/file-tools.

  const TOOLS_SECTION_ID = "afo-file-tools-section";

  function placeOnToolsPage() {
    if (document.getElementById(TOOLS_SECTION_ID)) return;
    // Stash keeps every settings tab in the page (only the open one shows),
    // so "the last section on the page" may belong to a hidden tab. The
    // Tools tab is found by its own links to Stash's tools instead, and the
    // section goes after the last section in that tab.
    const toolLink = document.querySelector('a[href$="/sceneFilenameParser"], a[href$="/sceneDuplicateChecker"]');
    const pane = toolLink && (toolLink.closest(".tab-pane") || toolLink.closest(".setting-section")?.parentElement);
    if (!pane) return;
    const sections = Array.from(pane.querySelectorAll(".setting-section"));
    const last = sections[sections.length - 1];
    if (!last) return;
    const heading = last.querySelector("h1, h2, h3, h4, h5, h6");

    const section = document.createElement(last.tagName.toLowerCase());
    section.id = TOOLS_SECTION_ID;
    section.className = last.className;
    const title = document.createElement(heading ? heading.tagName.toLowerCase() : "h1");
    if (heading) title.className = heading.className;
    title.textContent = "Scene Improvements";
    // Exactly the card of the tool sections above — same classes, so the
    // same width, background and text colour — with some inner spacing like
    // Stash's own tool rows. The tools are drawn inside that.
    const card = last.querySelector(".card");
    const box = document.createElement("div");
    box.className = card ? card.className : "card";
    const inner = document.createElement("div");
    inner.style.padding = "12px 16px";
    box.appendChild(inner);
    section.append(title, box);
    last.after(section);

    const view = h(FileToolsPage, { embedded: true });
    const ReactDOM = api.ReactDOM;
    if (ReactDOM && ReactDOM.createRoot) ReactDOM.createRoot(inner).render(view);
    else if (ReactDOM && ReactDOM.render) ReactDOM.render(view, inner);
  }

  let toolsPending = false;
  new MutationObserver(() => {
    if (toolsPending) return;
    toolsPending = true;
    setTimeout(() => {
      toolsPending = false;
      placeOnToolsPage();
    }, 300);
  }).observe(document.body, { childList: true, subtree: true });
})();
