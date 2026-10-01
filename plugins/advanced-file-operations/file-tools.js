// Advanced File Operations — File Tools page
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
// A button in the top navigation bar opens the page — on by default,
// switchable with the "Show a File Tools button in the top bar" setting.

(function () {
  "use strict";

  const api = window.PluginApi;
  if (!api || !api.React || !api.register || !api.register.route) return;
  const React = api.React;
  const h = React.createElement;
  const { useState, useEffect, useMemo } = React;
  const { Link, NavLink } = api.libraries.ReactRouterDOM;
  const FA = api.libraries.FontAwesomeSolid || {};

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

    const run = async () => {
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
        setError(err.message || String(err));
      } finally {
        setRunning(false);
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
            h("div", { style: muted }, r.torrent)),
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
          placeholder: "Folder with .torrent files (empty: the plugin setting)",
          onChange: (e) => setFolder(e.target.value),
          onKeyDown: (e) => { if (e.key === "Enter" && !running) run(); },
        }),
        h("button", { type: "button", className: "btn btn-primary", disabled: running, onClick: run },
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

  function FileToolsPage() {
    const [tab, setTab] = useState(remembered().tab || "torrents");
    const choose = (t) => {
      remember({ tab: t });
      setTab(t);
    };
    const tabButton = (value, text) => h("li", { className: "nav-item", key: value },
      h("a", {
        href: "#", className: `nav-link${tab === value ? " active" : ""}`,
        onClick: (e) => { e.preventDefault(); choose(value); },
      }, text));
    return h("div", { className: "container-fluid", style: { padding: "16px 24px" } },
      h("h2", null, "File Tools"),
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

  // -- the top bar button (setting, on by default) -----------------------------
  //
  // Stash settings can't declare a default, so the first time the setting
  // is missing it's saved as on — the switch then shows what happens.
  let buttonWanted = false;
  const listeners = new Set();
  gql("query { configuration { plugins } }")
    .then(async (data) => {
      const settings = (data.configuration.plugins || {})[PLUGIN_ID] || {};
      if (typeof settings.showToolsButton !== "boolean") {
        settings.showToolsButton = true;
        await gql(
          "mutation($plugin_id: ID!, $input: Map!) { configurePlugin(plugin_id: $plugin_id, input: $input) }",
          { plugin_id: PLUGIN_ID, input: settings }
        ).catch(() => {});
      }
      buttonWanted = settings.showToolsButton === true;
      listeners.forEach((redraw) => redraw());
    })
    .catch((err) => console.warn("[Advanced File Operations] Couldn't read plugin settings:", err));

  function ToolsButton() {
    const [, redraw] = useState(0);
    useEffect(() => {
      const listener = () => redraw((n) => n + 1);
      listeners.add(listener);
      return () => listeners.delete(listener);
    }, []);
    if (!buttonWanted) return null;
    const Icon = api.components && api.components.Icon;
    const Button = api.libraries.Bootstrap && api.libraries.Bootstrap.Button;
    const content = Icon && FA.faToolbox ? h(Icon, { icon: FA.faToolbox }) : "Tools";
    return h(NavLink, { className: "nav-utility", to: ROUTE, title: "File Tools" },
      Button ? h(Button, { className: "minimal d-flex align-items-center h-100", title: "File Tools" }, content) : content);
  }

  if (api.patch && api.patch.before) {
    api.patch.before("MainNavBar.UtilityItems", function (props) {
      return [{ ...props, children: h(React.Fragment, null, props.children, h(ToolsButton)) }];
    });
  }
})();
