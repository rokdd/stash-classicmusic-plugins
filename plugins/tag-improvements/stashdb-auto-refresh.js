// Tag Improvements — automatic refresh of StashDB tag descriptions
//
// Stash has no scheduler for plugin tasks, so this starts the "Update tag
// descriptions from StashDB" task itself: once per page load, if the last
// automatic run is older than the "Refresh every … days" setting. The time
// of that run is saved in the plugin's own settings (as `lastAutoRefresh`,
// which isn't shown in the settings page), so it counts across browsers
// and devices, not per browser.

(function () {
  "use strict";

  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "tagTree";
  const DEFAULT_REFRESH_DAYS = 7;
  // Wait a little after the page loads, so this doesn't compete with
  // Stash's own requests while the page is still building up.
  const START_DELAY_MS = 30000;

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

  async function refreshIfDue() {
    const data = await callGQL("query { configuration { plugins } }");
    const settings = (data.configuration.plugins || {})[PLUGIN_ID] || {};
    const days = typeof settings.refreshDays === "number" ? settings.refreshDays : DEFAULT_REFRESH_DAYS;
    if (days <= 0) return; // automatic refresh switched off
    const last = Number(settings.lastAutoRefresh || 0);
    if (Date.now() - last < days * 86400000) return;

    // Save the time first, so another open tab doesn't start it as well.
    // configurePlugin replaces all of the plugin's settings, hence the merge.
    await callGQL(
      "mutation($plugin_id: ID!, $input: Map!) { configurePlugin(plugin_id: $plugin_id, input: $input) }",
      { plugin_id: PLUGIN_ID, input: { ...settings, lastAutoRefresh: Date.now() } }
    );
    await callGQL(
      "mutation($plugin_id: ID!, $description: String, $args_map: Map) { runPluginTask(plugin_id: $plugin_id, description: $description, args_map: $args_map) }",
      {
        plugin_id: PLUGIN_ID,
        description: "Update tag descriptions from StashDB (automatic)",
        args_map: { mode: "sync_all" },
      }
    );
  }

  setTimeout(() => {
    refreshIfDue().catch((err) => console.warn("[Tag Improvements] Automatic StashDB refresh failed:", err));
  }, START_DELAY_MS);
})();
