// Tag Tree — UI addon
//
// Adds a page at /plugin/tag-tree that shows every tag as a collapsible
// tree of parents and children, and a button in the top navigation bar
// that opens it. Each tag shows its image (if it has a custom one), its
// description, its scene and marker counts, and links to its own tag page.
//
// The page also has the manual controls for this plugin's StashDB side
// (stashdb_tag_descriptions.py): a button that updates every tag's
// description from StashDB, and a ↻ per tag linked to StashDB.
//
// A tag with several parents appears under each of them. A tag that is
// (through some chain) its own ancestor is shown once on that path and
// not expanded again, so a loop in the hierarchy can't hang the page.
//
// Written against Stash's PluginApi (v0.25+): register.route for the page,
// patch.before("MainNavBar.UtilityItems") for the navbar button. Plain
// React.createElement instead of JSX, since plugins aren't compiled.

(function () {
  "use strict";

  const api = window.PluginApi;
  if (!api || !api.React || !api.register || !api.register.route) {
    console.warn("[Tag Tree] This Stash version has no PluginApi.register.route — the tag tree needs Stash v0.25 or newer.");
    return;
  }

  const React = api.React;
  const h = React.createElement;
  const { useState, useEffect, useMemo, useCallback } = React;
  const { Link, NavLink } = api.libraries.ReactRouterDOM;
  const FA = api.libraries.FontAwesomeSolid || {};

  const ROUTE = "/plugin/tag-tree";
  const IMAGE_HEIGHT_PX = 56;

  // Remembered per browser: which branches were open, so coming back to
  // the page doesn't collapse everything again. Wrapped in try/catch since
  // storage can be unavailable (private windows, blocked site data).
  const STORAGE_KEY = "tagTree.expanded";
  function loadExpanded() {
    try {
      return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]"));
    } catch (e) {
      return new Set();
    }
  }
  function saveExpanded(set) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(set)));
    } catch (e) {
      // Not remembered this time — nothing else depends on it.
    }
  }

  // -- data ---------------------------------------------------------------

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

  // Every tag in one request (per_page -1 means "all" to Stash).
  async function fetchAllTags() {
    const data = await callGQL(`
      query {
        findTags(filter: { per_page: -1, sort: "name", direction: ASC }) {
          tags {
            id
            name
            aliases
            description
            image_path
            stash_ids { endpoint }
            scene_count
            scene_marker_count
            parents { id }
            children { id }
          }
        }
      }`);
    return data.findTags.tags;
  }

  // Starts one of this plugin's tasks (see stashdb_tag_descriptions.py) and
  // resolves once it has finished, by following the job in Stash's task
  // queue — so the page can reload the tags and show the new descriptions.
  const PLUGIN_ID = "tagTree";
  const DONE_STATUSES = new Set(["FINISHED", "CANCELLED", "STOPPED", "FAILED"]);
  async function runTaskAndWait(description, argsMap) {
    const data = await callGQL(
      "mutation($plugin_id: ID!, $description: String, $args_map: Map) { runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map) }",
      { plugin_id: PLUGIN_ID, description, args_map: argsMap }
    );
    const jobId = data.runPluginTask;
    if (!jobId) return;
    for (let i = 0; i < 400; i++) { // gives up after ~20 minutes
      await new Promise((resolve) => setTimeout(resolve, 3000));
      const job = (await callGQL("query($id: ID!) { findJob(input: { id: $id }) { status } }", { id: jobId })).findJob;
      if (!job || DONE_STATUSES.has(job.status)) return;
    }
  }

  // A tag without an uploaded image still has an image_path — Stash's
  // generic placeholder, marked with default=true.
  function hasCustomImage(tag) {
    if (!tag.image_path) return false;
    try {
      return new URL(tag.image_path, window.location.origin).searchParams.get("default") !== "true";
    } catch (e) {
      return !/[?&]default=true\b/.test(tag.image_path);
    }
  }

  // byId, children per tag (sorted by name) and the roots (tags without
  // parents). Parent/child ids pointing at tags that aren't in the list
  // are ignored.
  function buildIndex(tags) {
    const byId = new Map(tags.map((t) => [t.id, t]));
    const byName = (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    const childrenOf = new Map();
    tags.forEach((t) => {
      const kids = (t.children || []).map((c) => byId.get(c.id)).filter(Boolean).sort(byName);
      childrenOf.set(t.id, kids);
    });
    const roots = tags.filter((t) => !(t.parents || []).some((p) => byId.has(p.id))).sort(byName);
    return { byId, childrenOf, roots };
  }

  // With a search: the ids of tags to show — every tag whose name or alias
  // contains the text, plus every ancestor on the way to it, so a match is
  // always shown in its place in the tree.
  function visibleForSearch(index, text) {
    const q = text.trim().toLowerCase();
    if (!q) return null;
    const matches = (t) =>
      t.name.toLowerCase().includes(q) || (t.aliases || []).some((a) => a.toLowerCase().includes(q));
    const visible = new Map(); // id → bool, also the memo
    const inProgress = new Set();
    const check = (t) => {
      if (visible.has(t.id)) return visible.get(t.id);
      if (inProgress.has(t.id)) return false; // loop in the hierarchy
      inProgress.add(t.id);
      let show = matches(t);
      for (const kid of index.childrenOf.get(t.id) || []) {
        if (check(kid)) show = true; // no early exit: memoize every child
      }
      inProgress.delete(t.id);
      visible.set(t.id, show);
      return show;
    };
    index.byId.forEach((t) => check(t));
    return new Set(Array.from(visible).filter(([, show]) => show).map(([id]) => id));
  }

  // Keys of every branch that has children, for "Expand all". A node's key
  // is its path from the root ("1/5/12"), since a tag with several parents
  // appears — and opens — separately under each.
  function allBranchKeys(index) {
    const keys = [];
    const walk = (t, path) => {
      const kids = index.childrenOf.get(t.id) || [];
      if (!kids.length || path.includes(t.id)) return;
      const next = [...path, t.id];
      keys.push(next.join("/"));
      kids.forEach((k) => walk(k, next));
    };
    index.roots.forEach((r) => walk(r, []));
    return keys;
  }

  // -- components ---------------------------------------------------------

  function Chevron({ open }) {
    const Icon = api.components && api.components.Icon;
    const icon = open ? FA.faChevronDown : FA.faChevronRight;
    return Icon && icon ? h(Icon, { icon }) : h("span", null, open ? "▾" : "▸");
  }

  function TagNode({ tag, path, ctx }) {
    const key = [...path, tag.id].join("/");
    const isLoop = path.includes(tag.id);
    const kids = isLoop
      ? []
      : (ctx.index.childrenOf.get(tag.id) || []).filter((k) => !ctx.visible || ctx.visible.has(k.id));
    const open = kids.length > 0 && (ctx.visible !== null || ctx.expanded.has(key));

    const counts = [];
    if (tag.scene_count) counts.push(`${tag.scene_count} scene${tag.scene_count === 1 ? "" : "s"}`);
    if (tag.scene_marker_count) counts.push(`${tag.scene_marker_count} marker${tag.scene_marker_count === 1 ? "" : "s"}`);

    const row = h(
      "div",
      { style: { display: "flex", alignItems: "center", gap: "8px", padding: "3px 0", minHeight: `${IMAGE_HEIGHT_PX + 6}px` } },
      kids.length
        ? h(
          "button",
          {
            type: "button",
            className: "btn btn-link p-0",
            style: { width: "20px", color: "inherit", flex: "none" },
            title: open ? "Collapse" : "Expand",
            onClick: () => ctx.toggle(key),
          },
          h(Chevron, { open })
        )
        : h("span", { style: { width: "20px", flex: "none" } }),
      hasCustomImage(tag)
        ? h("img", {
          src: tag.image_path,
          alt: "",
          loading: "lazy",
          style: {
            height: `${IMAGE_HEIGHT_PX}px`,
            width: "auto",
            maxWidth: `${IMAGE_HEIGHT_PX * 2}px`,
            objectFit: "contain",
            background: "rgba(255,255,255,0.92)",
            flex: "none",
          },
        })
        : null,
      h(
        "div",
        { style: { minWidth: 0, flex: "1" } },
        h(
          "div",
          { style: { display: "flex", alignItems: "baseline", flexWrap: "wrap", gap: "8px" } },
          h(Link, { to: `/tags/${tag.id}` }, tag.name),
          isLoop ? h("span", { className: "text-muted", style: { fontSize: "0.8em" } }, "(loop — already above)") : null,
          counts.length ? h("span", { className: "text-muted", style: { fontSize: "0.8em" } }, counts.join(" · ")) : null,
          (tag.stash_ids || []).length
            ? h("button", {
              type: "button",
              className: "btn btn-link btn-sm p-0",
              style: { fontSize: "0.8em" },
              title: "Update this tag's description from StashDB",
              disabled: ctx.busy.has(tag.id),
              onClick: () => ctx.refreshTag(tag),
            }, ctx.busy.has(tag.id) ? "updating…" : "↻ StashDB")
            : null
        ),
        tag.description
          ? h("div", {
            className: "text-muted",
            title: tag.description,
            style: { fontSize: "0.85em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" },
          }, tag.description)
          : null
      )
    );

    return h(
      "li",
      null,
      row,
      open
        ? h(
          "ul",
          { style: { listStyle: "none", margin: 0, paddingLeft: "24px", borderLeft: "1px solid rgba(255,255,255,0.12)" } },
          kids.map((k) => h(TagNode, { key: k.id, tag: k, path: [...path, tag.id], ctx }))
        )
        : null
    );
  }

  function TagTreePage() {
    const [tags, setTags] = useState(null);
    const [error, setError] = useState(null);
    const [search, setSearch] = useState("");
    const [expanded, setExpanded] = useState(loadExpanded);
    // Tag ids whose description is being updated right now ("all" = every tag).
    const [busy, setBusy] = useState(() => new Set());

    const reload = useCallback(
      () => fetchAllTags().then(setTags, (err) => setError(err.message || String(err))),
      []
    );
    useEffect(() => {
      reload();
    }, [reload]);

    const markBusy = useCallback((id, on) => {
      setBusy((prev) => {
        const next = new Set(prev);
        if (on) next.add(id);
        else next.delete(id);
        return next;
      });
    }, []);
    const runAndReload = useCallback(async (id, description, argsMap) => {
      markBusy(id, true);
      try {
        await runTaskAndWait(description, argsMap);
        await reload();
      } catch (err) {
        window.alert(`Couldn't update from StashDB: ${err.message || err}`);
      } finally {
        markBusy(id, false);
      }
    }, [markBusy, reload]);
    const refreshTag = useCallback(
      (tag) => runAndReload(tag.id, `Update description of "${tag.name}" from StashDB`, { mode: "sync_tag", tag_id: String(tag.id) }),
      [runAndReload]
    );
    const refreshAll = useCallback(
      () => runAndReload("all", "Update tag descriptions from StashDB", { mode: "sync_all" }),
      [runAndReload]
    );

    const index = useMemo(() => (tags ? buildIndex(tags) : null), [tags]);
    const visible = useMemo(() => (index ? visibleForSearch(index, search) : null), [index, search]);

    const updateExpanded = useCallback((next) => {
      setExpanded(next);
      saveExpanded(next);
    }, []);
    const toggle = useCallback((key) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        saveExpanded(next);
        return next;
      });
    }, []);

    let body;
    if (error) {
      body = h("div", { className: "text-danger" }, `Couldn't load tags: ${error}`);
    } else if (!index) {
      body = h("div", { className: "text-muted" }, "Loading tags…");
    } else {
      const roots = index.roots.filter((r) => !visible || visible.has(r.id));
      const ctx = { index, visible, expanded, toggle, busy, refreshTag };
      body = roots.length
        ? h("ul", { style: { listStyle: "none", margin: 0, padding: 0 } },
          roots.map((r) => h(TagNode, { key: r.id, tag: r, path: [], ctx })))
        : h("div", { className: "text-muted" }, search ? "No tag matches that search." : "No tags yet.");
    }

    const toolbar = h(
      "div",
      { style: { display: "flex", flexWrap: "wrap", gap: "8px", alignItems: "center", marginBottom: "16px" } },
      h("input", {
        type: "search",
        className: "form-control",
        placeholder: "Search tags and aliases…",
        value: search,
        onChange: (e) => setSearch(e.target.value),
        style: { maxWidth: "320px" },
      }),
      h("button", {
        type: "button",
        className: "btn btn-secondary",
        disabled: !index || visible !== null,
        onClick: () => updateExpanded(new Set(allBranchKeys(index))),
      }, "Expand all"),
      h("button", {
        type: "button",
        className: "btn btn-secondary",
        disabled: !index || visible !== null,
        onClick: () => updateExpanded(new Set()),
      }, "Collapse all"),
      h("button", {
        type: "button",
        className: "btn btn-secondary",
        disabled: !index || busy.has("all"),
        title: "Fetch the description of every tag linked to StashDB (runs as a task in Settings → Tasks)",
        onClick: refreshAll,
      }, busy.has("all") ? "Updating from StashDB…" : "Update descriptions from StashDB"),
      tags ? h("span", { className: "text-muted", style: { fontSize: "0.85em" } }, `${tags.length} tags`) : null
    );

    return h(
      "div",
      { className: "container-fluid", style: { padding: "16px 24px" } },
      h("h2", { style: { marginBottom: "12px" } }, "Tag tree"),
      toolbar,
      body
    );
  }

  api.register.route(ROUTE, TagTreePage);

  // A button in the top navigation bar, next to Stash's own utility
  // buttons, that opens the tree.
  if (api.patch && api.patch.before) {
    api.patch.before("MainNavBar.UtilityItems", function (props) {
      const Icon = api.components && api.components.Icon;
      const Button = api.libraries.Bootstrap && api.libraries.Bootstrap.Button;
      const content = Icon && FA.faSitemap ? h(Icon, { icon: FA.faSitemap }) : "Tags";
      const link = h(
        NavLink,
        { className: "nav-utility", to: ROUTE, title: "Tag tree" },
        Button
          ? h(Button, { className: "minimal d-flex align-items-center h-100", title: "Tag tree" }, content)
          : content
      );
      return [{ ...props, children: h(React.Fragment, null, props.children, link) }];
    });
  }
})();
