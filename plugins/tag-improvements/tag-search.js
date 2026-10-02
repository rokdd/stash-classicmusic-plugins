// Tag Improvements — better tag search in every tag picker
//
// Stash's tag pickers (scene, marker, performer forms, filters …) search
// tag names and aliases for the text as typed. This answers their searches
// itself instead, from the whole tag list kept in the browser:
//   - every word you type has to appear somewhere — in any order — among a
//     tag's name, its aliases, its description and the names of the tags
//     above it ("symph beet" finds "Beethoven: Symphony No. 5");
//   - tags whose name matches come first.
// The pickers send these searches as FindTagsForSelect queries; this
// answers them in exactly that query's own shape, so the pickers can't tell
// the difference. The tag list is fetched with the picker's own query (so
// it has every field the picker needs), and fetched again when tags change.
// Searches by id (loading tags already picked) and by StashDB ID go to the
// server as usual, and if anything here goes wrong, so does the search.
//
// Other plugins can narrow the results: window.TagImprovementsSearch.
// addFilter(fn) — fn(tag, ancestorIds, ancestorNames) returns false to leave
// a tag out (names lower case)
// (Marker Improvements uses this for its "Marker tags" settings).
//
// Also a switch at the top of every tag dropdown, "Larger, with images":
// the dropdown uses most of the window's height, shows each tag's image and
// description, and closes once a tag is picked (remembered per browser;
// the "Large tag dropdown" setting is how it starts).

(function () {
  "use strict";

  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "tagTree";
  const CACHE_MS = 5 * 60 * 1000;
  const TAG_CHANGE = /\b(tagCreate|tagUpdate|tagDestroy|tagsDestroy|tagsMerge|bulkTagUpdate)\b/;

  const originalFetch = window.fetch;
  if (typeof originalFetch !== "function" || originalFetch.__tagSearchWrapped) return;

  const filters = [];
  // handles(): whether this answers tag searches itself (false with the
  // "Use Stash's plain tag search" setting) — so other plugins know whether
  // to narrow searches themselves instead.
  let handling = true;
  window.TagImprovementsSearch = { addFilter: (fn) => filters.push(fn), handles: () => handling };

  // -- settings -------------------------------------------------------------------

  let settings = null;
  function loadSettings() {
    if (!settings) {
      settings = originalFetch("/graphql", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "query { configuration { plugins } }" }),
      })
        .then((r) => r.json())
        .then((json) => (json.data.configuration.plugins || {})[PLUGIN_ID] || {})
        .catch(() => ({}))
        .then((s) => {
          handling = s.plainTagSearch !== true;
          return s;
        });
    }
    return settings;
  }

  // -- the tag list ------------------------------------------------------------------

  let cache = null; // { at, tags, byId, resultTypename, search: Map(id → text) }

  async function loadTags(query, init) {
    if (cache && Date.now() - cache.at < CACHE_MS) return cache;
    const body = JSON.stringify({
      operationName: "FindTagsForSelect",
      query,
      variables: { filter: { per_page: -1, sort: "name", direction: "ASC" } },
    });
    const response = await originalFetch("/graphql", { ...init, body });
    const json = await response.json();
    const found = json.data.findTags;
    const byId = new Map(found.tags.map((t) => [String(t.id), t]));
    const ancestorIds = (t) => {
      const out = new Set();
      const stack = (t.parents || []).map((p) => String(p.id));
      while (stack.length) {
        const id = stack.pop();
        if (out.has(id)) continue;
        out.add(id);
        const p = byId.get(id);
        if (p) (p.parents || []).forEach((pp) => stack.push(String(pp.id)));
      }
      return out;
    };
    const entries = found.tags.map((t) => {
      const ancestors = ancestorIds(t);
      const parentNames = Array.from(ancestors).map((id) => (byId.get(id) || {}).name || "");
      return {
        tag: t,
        ancestors,
        ancestorNames: parentNames.map((n) => n.toLowerCase()),
        name: (t.name || "").toLowerCase(),
        aliases: (t.aliases || []).join(" ").toLowerCase(),
        rest: [t.description || "", ...parentNames].join(" ").toLowerCase(),
      };
    });
    cache = { at: Date.now(), entries, resultTypename: found.__typename };
    return cache;
  }

  // Every word somewhere in name, aliases, description or parent names; the
  // better the name matches, the earlier.
  function search(entries, q, limit) {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const scored = [];
    entries.forEach((e) => {
      if (filters.some((f) => f(e.tag, e.ancestors, e.ancestorNames) === false)) return;
      const all = `${e.name} ${e.aliases} ${e.rest}`;
      if (!words.every((w) => all.includes(w))) return;
      let score = 5;
      const phrase = words.join(" ");
      if (!words.length) score = 0;
      else if (e.name === phrase) score = 0;
      else if (e.name.startsWith(phrase)) score = 1;
      else if (words.every((w) => e.name.includes(w))) score = 2;
      else if (words.every((w) => `${e.name} ${e.aliases}`.includes(w))) score = 3;
      else if (words.some((w) => e.name.includes(w))) score = 4;
      scored.push({ e, score });
    });
    scored.sort((a, b) => a.score - b.score || a.e.name.localeCompare(b.e.name));
    return { count: scored.length, tags: scored.slice(0, limit > 0 ? limit : scored.length).map((s) => s.e.tag) };
  }

  async function answer(input, init, request) {
    const s = await loadSettings();
    if (s.plainTagSearch === true) return null; // Stash's own search, please
    const cached = await loadTags(request.query, init);
    const vars = request.variables || {};
    const filter = vars.filter || {};
    const result = search(cached.entries, filter.q || "", filter.per_page);
    const json = {
      data: { findTags: { __typename: cached.resultTypename || "FindTagsResultType", count: result.count, tags: result.tags } },
    };
    return new Response(JSON.stringify(json), { status: 200, headers: { "Content-Type": "application/json" } });
  }

  // Stash (v0.31) always sends a tag_filter, usually an empty one ({}).
  // Only one with an actual criterion in it (e.g. the StashDB ID search) is
  // a search of its own, for the server.
  function hasCriteria(value) {
    if (value == null) return false;
    if (Array.isArray(value)) return value.some(hasCriteria);
    if (typeof value === "object") return Object.values(value).some(hasCriteria);
    return value !== "";
  }

  const wrapped = function (input, init) {
    const body = init && typeof init.body === "string" ? init.body : "";
    if (TAG_CHANGE.test(body)) cache = null; // tags changed: fetch the list again next time
    if (body.includes("FindTagsForSelect")) {
      let request = null;
      try {
        request = JSON.parse(body);
      } catch (e) {
        // not JSON: leave it to Stash
      }
      const vars = (request && request.variables) || {};
      // Loading picked tags by id, or a search with Stash's own filter (e.g.
      // by StashDB ID): the server's job, as usual.
      const ours = request && request.query && !(vars.ids && vars.ids.length) && !hasCriteria(vars.tag_filter);
      if (ours) {
        const self = this;
        const args = arguments;
        return answer(input, init, request)
          .then((response) => response || originalFetch.apply(self, args))
          .catch((err) => {
            console.warn("[Tag Improvements] Tag search fell back to Stash's own:", err);
            return originalFetch.apply(self, args);
          });
      }
    }
    return originalFetch.apply(this, arguments);
  };
  wrapped.__tagSearchWrapped = true;
  window.fetch = wrapped;

  // -- large tag dropdown ---------------------------------------------------------------
  //
  // Every tag dropdown gets a switch at its top: "Larger, with images" makes
  // it use most of the window's height and shows each tag's image and
  // description; it then closes once a tag is picked. The choice is kept in
  // this browser; the "Large tag dropdown" setting is how it starts.

  const LARGE_KEY = "tagImprovements.largeTagDropdown";
  const LARGE_CLASS = "tag-search-large";
  const MENU_CLASS = "tag-search-menu";
  const SWITCH_CLASS = "tag-search-switch";

  function readLarge(fallback) {
    try {
      const v = window.localStorage.getItem(LARGE_KEY);
      return v == null ? fallback : v === "1";
    } catch (e) {
      return fallback;
    }
  }
  function writeLarge(on) {
    try {
      window.localStorage.setItem(LARGE_KEY, on ? "1" : "0");
    } catch (e) {
      // not remembered then
    }
  }

  loadSettings().then((s) => {
    let large = readLarge(s.largeTagDropdown === true);
    const root = document.documentElement;
    root.classList.toggle(LARGE_CLASS, large);

    const LIST = '[class*="react-select__menu-list"]';
    const large_ = `.${LARGE_CLASS} .${MENU_CLASS}`;
    const style = document.createElement("style");
    style.textContent = [
      // Large: a panel the whole height of the window, in front of the page
      // (wherever Stash put the dropdown — above the field, it would grow
      // off the top of the screen). What's typed shows in its top bar.
      `${large_} { position: fixed !important; top: 8px !important; bottom: 8px !important; left: 50% !important;` +
        " right: auto !important; transform: translateX(-50%); width: min(760px, 96vw) !important; margin: 0 !important;" +
        " z-index: 2000 !important; display: flex !important; flex-direction: column;" +
        " box-shadow: 0 0 0 100vmax rgba(0,0,0,.45) !important; }",
      `${large_} ${LIST} { max-height: none !important; flex: 1 1 auto; min-height: 0; position: static !important; }`,
      `.${SWITCH_CLASS} { display: flex; align-items: center; gap: 8px; padding: 4px 10px; font-size: 0.8em;` +
        " border-bottom: 1px solid rgba(128,128,128,.3); }",
      `.${SWITCH_CLASS} .tag-search-query { flex: 1; opacity: .75; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }`,
      `.${SWITCH_CLASS} button { margin-left: auto; background: none; border: 0; padding: 0; color: inherit; opacity: .75; cursor: pointer; }`,
      `.${SWITCH_CLASS} button:hover { opacity: 1; text-decoration: underline; }`,
      // Parent tags after the name, greyed out — always.
      ".tag-search-parents { margin-left: 6px; opacity: .6; font-size: .85em; }",
      // Large: the image floats on the left, name and description beside it.
      ".tag-search-extra > .tag-search-image, .tag-search-extra > .tag-search-description { display: none; }",
      `${large_} .tag-search-extra { display: flow-root !important; min-height: 56px; padding-top: 4px !important; padding-bottom: 4px !important; }`,
      `${large_} .tag-search-extra > .tag-search-image { display: block; float: left; margin-right: 10px; height: 48px; width: auto;` +
        " max-width: 96px; object-fit: contain; background: #fff; }",
      `${large_} .tag-search-extra > .tag-search-description { display: -webkit-box; font-size: 0.8em; opacity: 0.75;` +
        " white-space: normal; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }",
    ].join("\n");
    document.head.appendChild(style);

    const setLarge = (on) => {
      large = on;
      writeLarge(on);
      root.classList.toggle(LARGE_CLASS, on);
      document.querySelectorAll(`.${SWITCH_CLASS} button`).forEach(labelSwitch);
      showQuery();
    };
    const labelSwitch = (button) => {
      button.textContent = large ? "⤡ Smaller" : "⤢ Larger, with images";
    };
    // What's typed in the field, shown in the bar (the large panel covers
    // the field itself).
    const showQuery = () => {
      const active = document.activeElement;
      const text = active && active.tagName === "INPUT" ? active.value : "";
      document.querySelectorAll(`.${SWITCH_CLASS} .tag-search-query`).forEach((q) => {
        q.textContent = large && text ? `Search: ${text}` : "";
      });
    };
    document.addEventListener("input", showQuery, true);

    // Each option gets its tag's image and description, from the tag list
    // (shown only while large). Only added around the option's own
    // content, never moving it — that content is React's, and it must stay
    // where React put it. Options are reused for other tags as you type, so
    // it's redone when the name changes.
    const ownName = (option) => {
      let text = "";
      option.childNodes.forEach((n) => {
        if (n.nodeType === 1 && /tag-search-|marker-symbols-parents/.test(n.className || "")) return;
        text += n.textContent;
      });
      return text.trim().toLowerCase();
    };
    const decorate = () => {
      if (!cache) return;
      const byName = new Map(cache.entries.map((e) => [e.name, e.tag]));
      document.querySelectorAll('[class*="react-select__menu-list"]').forEach((list) => {
        const options = list.querySelectorAll('[class*="react-select__option"]');
        // A tag dropdown: one whose options are tags.
        const isTagMenu = Array.from(options).some((o) => byName.has(ownName(o)));
        const menu = list.parentElement;
        if (!isTagMenu || !menu) return;
        menu.classList.add(MENU_CLASS); // React may reset its classes: re-added each time
        if (!menu.querySelector(`:scope > .${SWITCH_CLASS}`)) {
          const button = document.createElement("button");
          button.type = "button";
          labelSwitch(button);
          // mousedown, with the default prevented: the field keeps its focus,
          // so the dropdown stays open.
          button.addEventListener("mousedown", (e) => {
            e.preventDefault();
            e.stopPropagation();
            setLarge(!large);
          });
          const bar = document.createElement("div");
          bar.className = SWITCH_CLASS;
          const query = document.createElement("span");
          query.className = "tag-search-query";
          bar.appendChild(query);
          bar.appendChild(button);
          menu.insertBefore(bar, list);
          showQuery();
        }
        options.forEach((option) => {
          const name = ownName(option);
          if (option.dataset.tagSearchFor === name) return;
          option.dataset.tagSearchFor = name;
          option.querySelectorAll(":scope > .tag-search-image, :scope > .tag-search-description, :scope > .tag-search-parents")
            .forEach((n) => n.remove());
          option.classList.remove("tag-search-extra");
          const tag = byName.get(name);
          if (!tag) return;
          // Parent tags after the name (Marker Improvements may have added
          // them already in the marker form).
          const parents = (tag.parents || []).map((p) => p.name).filter(Boolean).sort((a, b) => a.localeCompare(b));
          if (parents.length && !option.querySelector(".marker-symbols-parents")) {
            const hint = document.createElement("span");
            hint.className = "tag-search-parents";
            hint.textContent = `(${parents.join(", ")})`;
            option.appendChild(hint);
          }
          const hasImage = tag.image_path && !/[?&]default=true\b/.test(tag.image_path);
          if (!hasImage && !tag.description) return;
          option.classList.add("tag-search-extra");
          if (hasImage) {
            const img = document.createElement("img");
            img.className = "tag-search-image";
            img.loading = "lazy";
            img.src = tag.image_path;
            img.alt = "";
            option.insertBefore(img, option.firstChild);
          }
          if (tag.description) {
            const d = document.createElement("div");
            d.className = "tag-search-description";
            d.textContent = tag.description;
            option.appendChild(d);
          }
        });
      });
    };
    let pending = false;
    new MutationObserver(() => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        decorate();
      });
    }).observe(document.body, { childList: true, subtree: true });

    // In the large dropdown, close it once a tag is picked — also in fields
    // that pick several tags, which normally stay open.
    document.addEventListener("click", (e) => {
      if (!large || !e.target.closest) return;
      const option = e.target.closest('[class*="react-select__option"]');
      if (!option || !option.closest(`.${MENU_CLASS}`)) return;
      setTimeout(() => {
        const active = document.activeElement;
        if (active && active.blur) active.blur();
      }, 0);
    }, true);
  });
})();
