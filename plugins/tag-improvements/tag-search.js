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
// Also the "Large tag dropdown" setting: the dropdown uses most of the
// window's height, shows each tag's image and description, and closes
// once a tag is picked.

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

  // -- large tag dropdown (setting) -------------------------------------------------------

  loadSettings().then((s) => {
    if (s.largeTagDropdown !== true) return;

    const style = document.createElement("style");
    style.textContent = [
      ".react-select__menu-list { max-height: 75vh !important; }",
      // Image on the left, spanning the name and description rows.
      ".tag-search-extra { display: grid !important; grid-template-columns: auto 1fr; column-gap: 8px; align-items: start; }",
      ".tag-search-extra > .tag-search-image { grid-row: span 2; height: 48px; width: auto; max-width: 96px;" +
        " object-fit: contain; background: #fff; }",
      ".tag-search-extra > .tag-search-description { font-size: 0.8em; opacity: 0.75; white-space: normal;" +
        " display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }",
    ].join("\n");
    document.head.appendChild(style);

    // Each option gets its tag's image and description, from the tag list.
    // Only added around the option's own content, never moving it — that
    // content is React's, and it must stay where React put it. Options are
    // reused for other tags as you type, so it's redone when the name changes.
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
      document.querySelectorAll('[class*="react-select__option"]').forEach((option) => {
        const name = ownName(option);
        if (option.dataset.tagSearchFor === name) return;
        option.dataset.tagSearchFor = name;
        option.querySelectorAll(":scope > .tag-search-image, :scope > .tag-search-description").forEach((n) => n.remove());
        option.classList.remove("tag-search-extra");
        const tag = byName.get(name);
        if (!tag) return;
        const hasImage = tag.image_path && !/[?&]default=true\b/.test(tag.image_path);
        if (!hasImage && !tag.description) return;
        option.classList.add("tag-search-extra");
        if (hasImage) {
          const img = document.createElement("img");
          img.className = "tag-search-image";
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

    // Close the dropdown once a tag is picked — also in fields that pick
    // several tags, which normally stay open.
    document.addEventListener("click", (e) => {
      if (!e.target.closest || !e.target.closest('[class*="react-select__option"]')) return;
      setTimeout(() => {
        const active = document.activeElement;
        if (active && active.blur) active.blur();
      }, 0);
    }, true);
  });
})();
