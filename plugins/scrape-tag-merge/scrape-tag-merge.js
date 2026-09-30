// Scrape Tag Merge — UI addon
//
// On a scene's Edit tab, "Scrape with…" (a scraper or StashDB) normally
// *replaces* the scene's tags with the scraped ones: Stash's scrape dialog
// offers the scraped tag list as the new value, as a whole. This makes it
// offer existing + scraped tags instead.
//
// How: the dialog gets its data from Stash's GraphQL scrape queries
// (scrapeSingleScene, scrapeSceneURL). This wraps the page's fetch() and,
// for those answers only, adds the scene's current tags to each scraped
// scene's `tags` list — first, followed by the scraped tags that aren't
// already among them. The dialog then shows the union and works as usual:
// tags can still be removed before applying, the left (existing) side can
// still be picked, and scraped tags Stash couldn't match to a local tag
// keep their create/link buttons.
//
// Only on a scene's own page (so not the Tagger, which merges by itself),
// and only when the "Replace tags instead" setting is off.

(function () {
  "use strict";

  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "sceneScrapeTagMerge";

  const originalFetch = window.fetch;
  if (typeof originalFetch !== "function" || originalFetch.__scrapeTagMergeWrapped) return;

  function gql(query, variables) {
    return originalFetch("/graphql", {
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

  // The "Replace tags instead" setting, read once per page load.
  let replaceTags = null;
  function readSetting() {
    if (replaceTags !== null) return Promise.resolve(replaceTags);
    return gql("query { configuration { plugins } }")
      .then((data) => {
        const settings = (data.configuration.plugins || {})[PLUGIN_ID] || {};
        replaceTags = settings.replaceTags === true;
        return replaceTags;
      })
      .catch(() => false); // can't tell: merge, the plugin's default
  }

  function sceneIdFromPage() {
    const match = window.location.pathname.match(/\/scenes\/(\d+)/);
    return match ? match[1] : null;
  }

  // The scene's current tags, shaped like scraped tags (ScrapedTag with all
  // the fields Stash's scrape dialog asks for), marked as already matched
  // to a local tag through stored_id.
  async function currentTagsAsScraped(sceneId) {
    const data = await gql(
      "query($id: ID!) { findScene(id: $id) { tags { id name description aliases } } }",
      { id: sceneId }
    );
    return ((data.findScene && data.findScene.tags) || []).map((t) => ({
      __typename: "ScrapedTag",
      stored_id: t.id,
      name: t.name,
      description: t.description || null,
      alias_list: t.aliases || [],
      parent: null,
      remote_site_id: null,
    }));
  }

  // Existing tags first, then the scraped tags that aren't among them —
  // same local tag (stored_id) counts as the same. Scraped tags without a
  // stored_id (not matched to a local tag) are always kept, so their
  // create/link buttons still show.
  function mergeTags(existing, scraped) {
    const have = new Set(existing.map((t) => String(t.stored_id)));
    const merged = existing.slice();
    (scraped || []).forEach((t) => {
      if (t && t.stored_id != null && have.has(String(t.stored_id))) return;
      if (t && t.stored_id != null) have.add(String(t.stored_id));
      merged.push(t);
    });
    return merged;
  }

  function isSceneScrape(body) {
    return typeof body === "string" && /\b(scrapeSingleScene|scrapeSceneURL)\s*\(/.test(body);
  }

  async function mergeIntoResponse(response, requestBody) {
    if (await readSetting()) return response; // "replace", like Stash itself
    let request;
    try {
      request = JSON.parse(requestBody);
    } catch (e) {
      return response;
    }
    const input = (request.variables && request.variables.input) || {};
    const sceneId = input.scene_id || sceneIdFromPage();
    if (!sceneId) return response;

    let json;
    try {
      json = await response.clone().json();
    } catch (e) {
      return response;
    }
    const data = json && json.data;
    if (!data) return response;

    const existing = await currentTagsAsScraped(String(sceneId));
    if (!existing.length) return response;

    const results = []
      .concat(Array.isArray(data.scrapeSingleScene) ? data.scrapeSingleScene : [])
      .concat(data.scrapeSceneURL ? [data.scrapeSceneURL] : []);
    let changed = false;
    results.forEach((scene) => {
      // No scraped tags at all: Stash already keeps the existing ones.
      if (scene && Array.isArray(scene.tags) && scene.tags.length) {
        scene.tags = mergeTags(existing, scene.tags);
        changed = true;
      }
    });
    if (!changed) return response;

    return new Response(JSON.stringify(json), {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  }

  const wrappedFetch = function (input, init) {
    const result = originalFetch.apply(this, arguments);
    const body = init && init.body;
    if (!isSceneScrape(body) || !sceneIdFromPage()) return result;
    // Anything going wrong here must not break the scrape itself: fall
    // back to Stash's own answer.
    return result.then((response) =>
      mergeIntoResponse(response, body).catch((err) => {
        console.warn("[Scrape Tag Merge] Couldn't merge tags; showing the scrape as it came:", err);
        return response;
      })
    );
  };
  wrappedFetch.__scrapeTagMergeWrapped = true;
  window.fetch = wrappedFetch;
})();
