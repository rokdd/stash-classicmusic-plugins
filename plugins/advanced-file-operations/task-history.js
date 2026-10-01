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
  // Laid out like Stash's own task queue — one entry per task with a
  // status icon, the description and a line below — but with colours of
  // its own, so it's readable whatever Stash's styles do. Where a queued
  // task has a stop button, a finished one here has a button to remove it.

  if (!api || !api.React) return;
  const React = api.React;
  const h = React.createElement;
  const { useState, useEffect, useLayoutEffect, useCallback, useMemo, useRef } = React;

  // Whether `el` really sits on a dark background: walks up to the first
  // element with a visible background colour and checks its brightness.
  function onDarkBackground(el) {
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const m = getComputedStyle(node).backgroundColor.match(/rgba?\(([^)]+)\)/);
      if (!m) continue;
      const [r, g, b, a = 1] = m[1].split(",").map((v) => parseFloat(v));
      if (a < 0.1) continue; // transparent: look further up
      return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
    }
    return true; // nothing found: Stash's default theme is dark
  }

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

  function TaskHistoryView() {
    const rootRef = useRef(null);
    const [dark, setDark] = useState(true);
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


    // No background of its own — it sits in the queue's own box (see
    // placeOnTasksPage) and takes that box's background. The text colours
    // are set explicitly to suit it (light on dark, dark on light), and no
    // Stash entry classes are used, which used to override them.
    useLayoutEffect(() => {
      if (rootRef.current) setDark(onDarkBackground(rootRef.current));
    }, [entries]);
    const TEXT = dark ? "#f2f2f2" : "#1e1e1e";
    const DIM = { color: dark ? "#b8c0c8" : "#5a6470", fontSize: "0.85em" };
    const ERROR = dark ? "#ff8a80" : "#b3261e";
    return h("div", { ref: rootRef, style: { color: TEXT } },
      h("div", { style: { display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", paddingBottom: "8px" } },
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
      error && h("div", { style: { color: ERROR } }, error),
      !entries && !error && h("div", { style: DIM }, "Loading…"),
      entries && !shown.length && h("div", { style: DIM },
        entries.length ? "No tasks with this status." : "No finished tasks yet — they appear here as they finish."),
      shown.length > 0 && h("ul", { style: { listStyle: "none", margin: 0, padding: 0 } },
        shown.map((e) => {
          const st = STATUS[e.status] || { label: e.status, icon: "faCircle", fallback: "•", color: "#9aa4ad" };
          const took = formatDuration(e.startTime, e.endTime);
          return h("li", {
            key: entryKey(e),
            style: {
              display: "flex", gap: "10px", alignItems: "flex-start", padding: "8px 0",
              borderTop: `1px solid ${dark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"}`, color: TEXT,
            },
          },
            h("button", {
              type: "button", title: "Remove from the history", onClick: () => remove(e),
              style: { background: "none", border: 0, color: "#9aa4ad", padding: "0 2px", cursor: "pointer", flex: "none" },
            }, icon("faXmark", "×")),
            h("span", { style: { color: st.color, flex: "none" }, title: st.label }, icon(st.icon, st.fallback)),
            h("div", { style: { minWidth: 0, flex: 1 } },
              h("div", { style: { color: TEXT, wordBreak: "break-word" } }, e.description),
              h("div", { style: DIM },
                `${st.label} ${formatTime(e.endTime || e.startTime || e.addTime)}${took ? ` · took ${took}` : ""}`),
              e.error && h("div", { style: { color: ERROR, fontSize: "0.85em", wordBreak: "break-word" } }, e.error)));
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

    // Built like the queue: a box with exactly the queue card's classes —
    // so the same width, margins and spacing — under a heading like the
    // queue's, in the same column. The readable panel goes inside the box.
    const box = document.createElement("div");
    box.className = queue.className;
    const section = queue.closest(".setting-section");
    let container;
    if (section) {
      // The queue sits in a settings section: a section of the same kind
      // right after it.
      const heading = section.querySelector("h1, h2, h3, h4, h5, h6");
      container = document.createElement(section.tagName.toLowerCase());
      container.className = section.className;
      const title = document.createElement(heading ? heading.tagName.toLowerCase() : "h1");
      if (heading) title.className = heading.className;
      title.textContent = "Task History";
      container.append(title, box);
      section.after(container);
    } else {
      // Otherwise: heading and box right after the queue's own box, in the
      // same parent — the queue's heading (if it has one just above it)
      // copied for the look.
      const prev = queue.previousElementSibling;
      const heading = prev && /^H[1-6]$/.test(prev.tagName) ? prev : null;
      container = document.createElement("div");
      const title = document.createElement(heading ? heading.tagName.toLowerCase() : "h5");
      if (heading) title.className = heading.className;
      title.textContent = "Task History";
      container.append(title, box);
      queue.after(container);
    }
    container.id = CONTAINER_ID;
    const body = box;

    const view = h(TaskHistoryView);
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
