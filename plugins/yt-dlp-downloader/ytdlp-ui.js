// yt-dlp Downloader — UI addon
//
// A download button in Stash's top navigation bar opens a small dialog:
// paste one or more URLs (one per line; playlists work too), pick which of
// your library folders to save into (plus an optional subfolder) and the
// quality, and start. The download runs as a Stash task (see
// ytdlp_downloader.py); its progress shows in Settings → Tasks.
//
// The last folder, subfolder and quality are remembered in this browser.

(function () {
  "use strict";

  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "ytdlpDownloader";
  const REMEMBER_KEY = "ytdlpDownloader.lastChoice";

  const QUALITIES = [
    { value: "best", label: "Best available" },
    { value: "2160", label: "Up to 4K (2160p)" },
    { value: "1080", label: "Up to 1080p" },
    { value: "720", label: "Up to 720p" },
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
        if (json.errors) throw new Error(json.errors.map((e) => e.message).join("; "));
        return json.data;
      });
  }

  // Your library folders that take videos (Settings → Library).
  async function fetchLibraryPaths() {
    const data = await callGQL("query { configuration { general { stashes { path excludeVideo } } } }");
    return (data.configuration.general.stashes || []).filter((s) => !s.excludeVideo).map((s) => s.path);
  }

  function loadChoice() {
    try {
      return JSON.parse(localStorage.getItem(REMEMBER_KEY) || "{}");
    } catch (e) {
      return {};
    }
  }

  function saveChoice(choice) {
    try {
      localStorage.setItem(REMEMBER_KEY, JSON.stringify(choice));
    } catch (e) {
      // Not remembered this time — nothing else depends on it.
    }
  }

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    Object.assign(node, props || {});
    children.forEach((c) => node.append(c));
    return node;
  }

  async function openDialog() {
    let paths;
    try {
      paths = await fetchLibraryPaths();
    } catch (err) {
      window.alert(`Couldn't read your library folders: ${err.message || err}`);
      return;
    }
    if (!paths.length) {
      window.alert("You have no library folders for videos yet (Settings → Library).");
      return;
    }
    const last = loadChoice();

    const overlay = el("div");
    overlay.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:3000;display:flex;" +
      "align-items:center;justify-content:center;font-family:sans-serif;";
    const box = el("div");
    box.style.cssText =
      "background:#242730;color:#eee;padding:20px 24px;border-radius:8px;max-width:520px;width:92%;" +
      "max-height:85vh;overflow:auto;box-shadow:0 4px 24px rgba(0,0,0,0.5);display:flex;flex-direction:column;gap:12px;";
    overlay.appendChild(box);
    const close = () => overlay.remove();
    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) close();
    });

    box.appendChild(el("h5", { textContent: "Download with yt-dlp", style: "margin:0" }));

    const labelled = (text, input, hint) => {
      const wrap = el("label", { style: "display:flex;flex-direction:column;gap:4px;margin:0;font-size:0.9em;" }, text, input);
      if (hint) wrap.appendChild(el("span", { textContent: hint, style: "opacity:0.65;font-size:0.9em;" }));
      return wrap;
    };

    const urls = el("textarea", { className: "form-control", rows: 4, placeholder: "https://…\nhttps://…" });
    box.appendChild(labelled("Video or playlist URLs, one per line", urls));

    const dest = el("select", { className: "form-control" });
    paths.forEach((p) => dest.appendChild(el("option", { value: p, textContent: p })));
    if (paths.includes(last.dest)) dest.value = last.dest;
    box.appendChild(labelled("Save into library folder", dest));

    const subfolder = el("input", { className: "form-control", type: "text", value: last.subfolder || "", placeholder: "e.g. Concerts" });
    box.appendChild(labelled("Subfolder (optional)", subfolder, "Created if it doesn't exist yet."));

    const quality = el("select", { className: "form-control" });
    QUALITIES.forEach((q) => quality.appendChild(el("option", { value: q.value, textContent: q.label })));
    quality.value = last.quality || "best";
    box.appendChild(labelled("Quality", quality));

    const bg = el("input", { type: "checkbox", checked: false });
    bg.style.marginTop = "3px";
    box.appendChild(el(
      "label",
      { style: "display:flex;gap:8px;align-items:flex-start;margin:0;font-size:0.9em;cursor:pointer;" },
      bg,
      "Run in the background — Stash's task queue stays free while it downloads. Progress goes to a log " +
        "file on the server instead of Stash's progress bar."
    ));

    const buttons = el("div", { style: "display:flex;justify-content:flex-end;gap:8px;" });
    const cancel = el("button", { type: "button", className: "btn btn-secondary", textContent: "Cancel" });
    cancel.addEventListener("click", close);
    const start = el("button", { type: "button", className: "btn btn-primary", textContent: "Download" });
    start.addEventListener("click", async () => {
      const list = urls.value.split("\n").map((u) => u.trim()).filter(Boolean);
      if (!list.length) {
        window.alert("Paste at least one URL.");
        return;
      }
      const choice = { dest: dest.value, subfolder: subfolder.value.trim(), quality: quality.value };
      saveChoice(choice);
      start.disabled = true;
      start.textContent = "Starting…";
      try {
        const where = choice.subfolder ? `${choice.dest}/${choice.subfolder}` : choice.dest;
        await callGQL(
          "mutation($plugin_id: ID!, $description: String, $args_map: Map) { runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map) }",
          {
            plugin_id: PLUGIN_ID,
            description: `Download ${list.length} URL${list.length === 1 ? "" : "s"} to ${where}${bg.checked ? " (started in background)" : ""}`,
            args_map: { mode: "download", urls: list.join("\n"), ...choice, background: bg.checked ? "true" : "false" },
          }
        );
        start.textContent = "Queued ✓ — see Settings → Tasks";
        setTimeout(close, 1500);
      } catch (err) {
        window.alert(`Couldn't start the download: ${err.message || err}`);
        start.disabled = false;
        start.textContent = "Download";
      }
    });
    buttons.append(cancel, start);
    box.appendChild(buttons);

    document.body.appendChild(overlay);
    urls.focus();
  }

  // The button in the top navigation bar, next to Stash's own utility
  // buttons (Stash v0.25+ PluginApi). Without it, a small floating button.
  const api = window.PluginApi;
  if (api && api.patch && api.patch.before && api.React) {
    const h = api.React.createElement;
    const FA = (api.libraries && api.libraries.FontAwesomeSolid) || {};
    api.patch.before("MainNavBar.UtilityItems", function (props) {
      const Icon = api.components && api.components.Icon;
      const Button = api.libraries.Bootstrap && api.libraries.Bootstrap.Button;
      const content = Icon && FA.faDownload ? h(Icon, { icon: FA.faDownload }) : "⤓";
      const button = Button
        ? h(Button, { className: "minimal d-flex align-items-center h-100", title: "Download with yt-dlp", onClick: openDialog }, content)
        : h("button", { type: "button", className: "btn minimal", title: "Download with yt-dlp", onClick: openDialog }, content);
      return [{ ...props, children: h(api.React.Fragment, null, props.children, button) }];
    });
  } else {
    const button = el("button", { type: "button", className: "btn btn-secondary", title: "Download with yt-dlp", textContent: "⤓ yt-dlp" });
    button.style.cssText = "position:fixed;bottom:16px;left:16px;z-index:2000;box-shadow:0 2px 8px rgba(0,0,0,0.4);";
    button.addEventListener("click", openDialog);
    document.body.appendChild(button);
  }
})();
