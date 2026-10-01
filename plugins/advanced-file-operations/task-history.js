// Advanced File Operations — task history
//
// Stash keeps no history of finished tasks: its task list only shows what's
// queued or running. This records every task as it finishes and shows the
// history — under the running tasks on Settings → Tasks, and as a tab on
// the File Tools page (file-tools.js uses window.AFOTaskHistory.View).
//
// Recording, while any Stash page is open: every few seconds the task list
// is read; a task that's gone from it has finished, and Stash still reports
// its final status for its last 10 finished tasks (findJob), so that's
// looked up and kept. On page load, tasks that finished while no page was
// open are picked up too, as long as they're among those last 10. The
// history lives on the server (task_history.py), shared by every browser;
// several open tabs recording the same task keep it once.

(function () {
  "use strict";

  const api = window.PluginApi;
  // Must match the filename of this plugin's yml manifest (minus .yml).
  const PLUGIN_ID = "advancedFileOperations";
  const DONE = new Set(["FINISHED", "CANCELLED", "FAILED"]);
  const JOB_FIELDS = "id status description addTime startTime endTime error";
  const CHANGED_EVENT = "afo:taskHistoryChanged";

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

  function operation(args) {
    return gql(
      "mutation($plugin_id: ID!, $args: Map) { runPluginOperation(plugin_id: $plugin_id, args: $args) }",
      { plugin_id: PLUGIN_ID, args }
    ).then((d) => d.runPluginOperation);
  }

  const findJob = (id) =>
    gql(`query($id: ID!) { findJob(input: { id: $id }) { ${JOB_FIELDS} } }`, { id: String(id) })
      .then((d) => d.findJob)
      .catch(() => null);

  async function save(jobs) {
    if (!jobs.length) return;
    const result = await operation({ mode: "history_add", entries: JSON.stringify(jobs) });
    if (result && result.added) window.dispatchEvent(new Event(CHANGED_EVENT));
  }

  // -- recording ----------------------------------------------------------------

  const running = new Map(); // id → last state seen in the task list

  async function poll() {
    const queue = (await gql(`query { jobQueue { ${JOB_FIELDS} } }`)).jobQueue || [];
    const inQueue = new Set(queue.map((j) => j.id));
    queue.forEach((j) => running.set(j.id, j));
    const finished = [];
    for (const id of Array.from(running.keys())) {
      if (inQueue.has(id)) continue;
      running.delete(id);
      const job = await findJob(id);
      if (job && DONE.has(job.status)) finished.push(job);
    }
    await save(finished);
  }

  // Tasks that finished while no page was open: Stash numbers tasks one
  // after another, so look at the ones after the last recorded, while it
  // still knows them. After a restart its numbering starts at 1 again.
  async function catchUp() {
    const { last_id: lastId } = await operation({ mode: "history_list" });
    const found = [];
    const probe = async (from) => {
      let misses = 0;
      for (let id = from; id < from + 60 && misses < 3; id++) {
        const job = await findJob(id);
        if (!job) {
          misses++;
          continue;
        }
        misses = 0;
        if (DONE.has(job.status)) found.push(job);
        else running.set(job.id, job);
      }
    };
    await probe(Number(lastId || 0) + 1);
    if (!found.length && lastId) await probe(1); // Stash restarted since
    await save(found);
  }

  function startRecording() {
    let busy = false;
    const tick = async () => {
      if (busy) return;
      busy = true;
      try {
        await poll();
      } catch (err) {
        // A failed check is simply tried again next time.
      } finally {
        busy = false;
      }
    };
    catchUp().catch((err) => console.warn("[Advanced File Operations] Task history catch-up failed:", err));
    // Every 3 seconds while the page is in view, every 15 otherwise.
    let timer = null;
    const schedule = () => {
      clearInterval(timer);
      timer = setInterval(tick, document.hidden ? 15000 : 3000);
    };
    document.addEventListener("visibilitychange", schedule);
    schedule();
  }

  startRecording();

  // -- the history view ------------------------------------------------------------

  if (!api || !api.React) return;
  const React = api.React;
  const h = React.createElement;
  const { useState, useEffect, useCallback, useMemo } = React;

  const STATUS = {
    FINISHED: { label: "Finished", color: "#2e9e4f" },
    FAILED: { label: "Failed", color: "#c0392b" },
    CANCELLED: { label: "Cancelled", color: "#6c757d" },
  };

  function formatTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  }

  function formatDuration(start, end) {
    const ms = new Date(end) - new Date(start);
    if (!start || !end || Number.isNaN(ms) || ms < 0) return "–";
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  function TaskHistoryView() {
    const [entries, setEntries] = useState(null);
    const [error, setError] = useState(null);
    const [filter, setFilter] = useState("all");

    const load = useCallback(() => {
      operation({ mode: "history_list" })
        .then((r) => setEntries(r.entries || []))
        .catch((err) => setError(err.message || String(err)));
    }, []);
    useEffect(() => {
      load();
      window.addEventListener(CHANGED_EVENT, load);
      return () => window.removeEventListener(CHANGED_EVENT, load);
    }, [load]);

    const clear = () => {
      if (!window.confirm("Clear the whole task history?")) return;
      operation({ mode: "history_clear" }).then(load).catch((err) => setError(err.message || String(err)));
    };

    const shown = useMemo(
      () => (entries || []).filter((e) => filter === "all" || e.status === filter),
      [entries, filter]
    );
    const cell = { padding: "6px 8px", verticalAlign: "top", borderTop: "1px solid rgba(255,255,255,0.1)" };

    return h("div", null,
      h("div", { style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", marginBottom: "8px" } },
        h("select", { className: "form-control", style: { maxWidth: "200px" }, value: filter, onChange: (e) => setFilter(e.target.value) },
          h("option", { value: "all" }, `All (${(entries || []).length})`),
          Object.keys(STATUS).map((s) => h("option", { key: s, value: s },
            `${STATUS[s].label} (${(entries || []).filter((e) => e.status === s).length})`))),
        h("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: load }, "Refresh"),
        h("button", { type: "button", className: "btn btn-secondary btn-sm", onClick: clear, disabled: !entries || !entries.length }, "Clear history")),
      error && h("div", { className: "text-danger" }, error),
      !entries && !error && h("div", { className: "text-muted" }, "Loading…"),
      entries && !shown.length && h("div", { className: "text-muted" },
        entries.length ? "No tasks with this status." : "No finished tasks recorded yet — they appear here as they finish."),
      shown.length > 0 && h("table", { style: { width: "100%", borderCollapse: "collapse", fontSize: "0.9em" } },
        h("thead", null, h("tr", null, ["Ended", "Task", "Status", "Duration"].map((t) =>
          h("th", { key: t, style: { ...cell, borderTop: "none", textAlign: "left" } }, t)))),
        h("tbody", null, shown.map((e) => {
          const st = STATUS[e.status] || { label: e.status, color: "#6c757d" };
          return h("tr", { key: `${e.id}|${e.addTime}` },
            h("td", { style: { ...cell, whiteSpace: "nowrap" } }, formatTime(e.endTime || e.startTime || e.addTime)),
            h("td", { style: { ...cell, wordBreak: "break-word" } },
              e.description,
              e.error && h("div", { className: "text-danger", style: { fontSize: "0.9em" } }, e.error)),
            h("td", { style: cell }, h("span", { className: "badge", style: { background: st.color, color: "#fff" } }, st.label)),
            h("td", { style: { ...cell, whiteSpace: "nowrap" } }, formatDuration(e.startTime, e.endTime)));
        }))));
  }

  window.AFOTaskHistory = { View: TaskHistoryView };

  // -- under the running tasks on Settings → Tasks ---------------------------------
  //
  // Stash's task list there (its "job-table") isn't a component plugins can
  // extend, so the history is placed right after it on the page. If a Stash
  // version builds that page differently, it just doesn't appear there — the
  // File Tools page's Task history tab still has it.

  const CONTAINER_ID = "afo-task-history";
  function placeOnTasksPage() {
    if (!/\/settings/.test(window.location.pathname) || !/tab=tasks/.test(window.location.search)) return;
    if (document.getElementById(CONTAINER_ID)) return;
    const jobTable = document.querySelector(".job-table");
    if (!jobTable) return;
    const container = document.createElement("div");
    container.id = CONTAINER_ID;
    container.className = "card";
    container.style.cssText = "padding:12px 16px;margin:16px 0;";
    const heading = document.createElement("h5");
    heading.textContent = "Task history";
    const body = document.createElement("div");
    container.append(heading, body);
    jobTable.after(container);
    const ReactDOM = api.ReactDOM;
    if (ReactDOM && ReactDOM.createRoot) ReactDOM.createRoot(body).render(h(TaskHistoryView));
    else if (ReactDOM && ReactDOM.render) ReactDOM.render(h(TaskHistoryView), body);
  }

  let placePending = false;
  new MutationObserver(() => {
    if (placePending) return;
    placePending = true;
    setTimeout(() => {
      placePending = false;
      placeOnTasksPage();
    }, 300);
  }).observe(document.body, { childList: true, subtree: true });
})();
