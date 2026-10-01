// Scene Improvements — task history
//
// Stash keeps no history of finished tasks: its task list only shows what's
// queued or running. This records every task as it finishes and shows the
// history — under the running tasks on Settings → Tasks, and as a tab on
// the Scene Improvements tools on Settings → Tools (file-tools.js uses
// window.AFOTaskHistory.View).
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
    catchUp().catch((err) => console.warn("[Scene Improvements] Task history catch-up failed:", err));
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
  //
  // Drawn like Stash's own task queue: the same card ("job-table") and the
  // same entries ("job" items with a status icon, the description, and a
  // line below), so it picks up Stash's own styling. Where a queued task
  // has a stop button, a finished one here has a button to remove it.

  if (!api || !api.React) return;
  const React = api.React;
  const h = React.createElement;
  const { useState, useEffect, useCallback, useMemo } = React;
  const FA = (api.libraries && api.libraries.FontAwesomeSolid) || {};

  const STATUS = {
    FINISHED: { label: "Finished", icon: "faCheck", fallback: "✓", color: "#2e9e4f" },
    FAILED: { label: "Failed", icon: "faCircleExclamation", fallback: "!", color: "#c0392b" },
    CANCELLED: { label: "Cancelled", icon: "faBan", fallback: "⊘", color: "#6c757d" },
  };

  function icon(name, fallback) {
    const Icon = api.components && api.components.Icon;
    const glyph = FA[name] || (name === "faCircleExclamation" && FA.faExclamationCircle);
    return Icon && glyph ? h(Icon, { icon: glyph, className: "fa-fw" }) : h("span", null, fallback);
  }

  function formatTime(iso) {
    if (!iso) return "–";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
  }

  function formatDuration(start, end) {
    const ms = new Date(end) - new Date(start);
    if (!start || !end || Number.isNaN(ms) || ms < 0) return "";
    const s = Math.round(ms / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ${s % 60}s`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
  }

  const entryKey = (e) => `${e.id}|${e.addTime}`;

  // `cardClassName` / `cardStyle`: on Settings → Tasks, taken from Stash's
  // own queue card above, so both look exactly alike (see placeOnTasksPage).
  function TaskHistoryView({ cardClassName, cardStyle } = {}) {
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

    const remove = (e) =>
      operation({ mode: "history_remove", key: entryKey(e) }).then(load).catch((err) => setError(err.message || String(err)));
    const clear = () => {
      if (!window.confirm("Clear the whole task history?")) return;
      operation({ mode: "history_clear" }).then(load).catch((err) => setError(err.message || String(err)));
    };

    const shown = useMemo(
      () => (entries || []).filter((e) => filter === "all" || e.status === filter),
      [entries, filter]
    );
    const count = (s) => (entries || []).filter((e) => e.status === s).length;

    return h("div", { className: cardClassName || "card job-table", style: cardStyle || { color: "inherit" } },
      h("div", { style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", padding: "0 0 8px" } },
        h("select", {
          className: "form-control form-control-sm", style: { maxWidth: "190px" }, value: filter,
          onChange: (e) => setFilter(e.target.value),
        },
          h("option", { value: "all" }, `All (${(entries || []).length})`),
          Object.keys(STATUS).map((s) => h("option", { key: s, value: s }, `${STATUS[s].label} (${count(s)})`))),
        h("button", {
          type: "button", className: "btn btn-secondary btn-sm", style: { marginLeft: "auto" },
          onClick: clear, disabled: !entries || !entries.length,
        }, "Clear history")),
      error && h("div", { className: "text-danger" }, error),
      h("ul", null,
        !entries && !error && h("span", { className: "empty-queue-message" }, "Loading…"),
        entries && !shown.length && h("span", { className: "empty-queue-message" },
          entries.length ? "No tasks with this status." : "No finished tasks yet — they appear here as they finish."),
        shown.map((e) => {
          const st = STATUS[e.status] || { label: e.status, icon: "faCircle", fallback: "•", color: "#6c757d" };
          const took = formatDuration(e.startTime, e.endTime);
          return h("li", { key: entryKey(e), className: `job ${String(e.status || "").toLowerCase()}` },
            h("div", null,
              h("button", {
                type: "button", className: "btn btn-sm minimal stop", title: "Remove from the history",
                onClick: () => remove(e),
              }, icon("faXmark", "×") ),
              h("div", { className: "job-status" },
                h("div", null,
                  h("span", { style: { color: st.color }, title: st.label }, icon(st.icon, st.fallback)),
                  " ",
                  h("span", null, e.description)),
                h("div", { style: { opacity: 0.7, fontSize: "0.85em" } },
                  `${st.label} ${formatTime(e.endTime || e.startTime || e.addTime)}${took ? ` · took ${took}` : ""}`),
                e.error && h("div", { className: "job-error" }, e.error))));
        })));
  }

  window.AFOTaskHistory = { View: TaskHistoryView };

  // -- underneath the task queue on Settings → Tasks ------------------------------
  //
  // Stash's queue there isn't a component plugins can extend, so the history
  // goes right after the queue's section on the page, built the same way:
  // the same kind of section and heading as the queue's, titled "Task
  // History". If a Stash version builds that page differently, it just
  // doesn't appear there — the Task history tab on Settings → Tools has it.

  const CONTAINER_ID = "afo-task-history";

  function placeOnTasksPage() {
    if (!/\/settings/.test(window.location.pathname) || !/tab=tasks/.test(window.location.search)) return;
    if (document.getElementById(CONTAINER_ID)) return;
    // Stash's own queue — not this history, which uses the same class.
    const queue = Array.from(document.querySelectorAll(".job-table")).find((el) => !el.closest(`#${CONTAINER_ID}`));
    if (!queue) return;

    // The queue's own section and heading, to copy their look.
    const section = queue.closest(".setting-section") || queue.parentElement;
    const heading = section && section.querySelector("h1, h2, h3, h4, h5, h6");
    const container = document.createElement(section ? section.tagName.toLowerCase() : "div");
    container.id = CONTAINER_ID;
    container.className = section ? section.className : "";
    const title = document.createElement(heading ? heading.tagName.toLowerCase() : "h1");
    if (heading) title.className = heading.className;
    title.textContent = "Task History";
    const body = document.createElement("div");
    container.append(title, body);
    (section || queue).after(container);

    // The queue card's own classes and its actual colours on the page, so
    // the text is as readable as the queue's whatever the theme.
    const look = getComputedStyle(queue);
    const view = h(TaskHistoryView, {
      cardClassName: queue.className,
      cardStyle: { color: look.color, backgroundColor: look.backgroundColor },
    });
    const ReactDOM = api.ReactDOM;
    if (ReactDOM && ReactDOM.createRoot) ReactDOM.createRoot(body).render(view);
    else if (ReactDOM && ReactDOM.render) ReactDOM.render(view, body);
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
