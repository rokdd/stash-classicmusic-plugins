// Face Identifier — "Who's in this scene?" in a scene's ⋮ menu: a dialog
// with the performers recognised by their faces (add them to the scene),
// the faces nobody's known by (say who it is: added, and learnt), and —
// if asked — what Visage finds. See face_identifier.py.
(function () {
  "use strict";

  const PLUGIN_ID = "faceIdentifier";
  const DIALOG_ID = "face-identifier-dialog";

  function gql(query, variables) {
    return fetch("/graphql", { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, variables }) })
      .then((r) => r.json())
      .then((json) => { if (json.errors) throw new Error(json.errors.map((e) => e.message).join("; ")); return json.data; });
  }

  async function run(args) {
    const data = await gql("mutation($p: ID!, $a: Map) { runPluginOperation(plugin_id: $p, args: $a) }", { p: PLUGIN_ID, a: args });
    const r = data.runPluginOperation;
    if (r && typeof r === "object" && r.error) throw new Error(r.error);
    return r;
  }

  function sceneId() {
    const m = window.location.pathname.match(/\/scenes\/(\d+)/);
    return m ? m[1] : null;
  }

  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (k === "style") Object.assign(n.style, v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k in n) n[k] = v;
      else n.setAttribute(k, v);
    });
    kids.flat().forEach((c) => c != null && c !== false && n.append(c.nodeType ? c : String(c)));
    return n;
  }

  const clock = (s) => { s = Math.round(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return `${h ? `${h}:${String(m).padStart(2, "0")}` : m}:${String(s % 60).padStart(2, "0")}`; };

  function seek(t) {
    const v = document.querySelector("video");
    if (v) { v.currentTime = t; v.play().catch(() => {}); }
  }

  // -- the dialog --------------------------------------------------------------------------------

  function dialog(title) {
    const old = document.getElementById(DIALOG_ID);
    if (old) old.remove();
    const body = el("div", { className: "modal-body", style: { maxHeight: "75vh", overflowY: "auto" } });
    const footer = el("div", { className: "modal-footer" });
    const close = () => wrap.remove();
    footer.append(el("button", { type: "button", className: "btn btn-secondary", textContent: "Close", onclick: close }));
    const wrap = el("div", { id: DIALOG_ID },
      el("div", { className: "modal-backdrop show", onclick: close }),
      el("div", { className: "modal d-block", tabIndex: -1, onclick: (e) => { if (e.target === e.currentTarget) close(); } },
        el("div", { className: "modal-dialog modal-xl" },
          el("div", { className: "modal-content" },
            el("div", { className: "modal-header" }, el("h5", { className: "modal-title", textContent: title })), body, footer))));
    document.body.append(wrap);
    if (!document.getElementById("fi-style")) {
      document.head.append(el("style", { id: "fi-style", textContent: [
        ".fi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }",
        ".fi-card { background: rgba(255,255,255,.05); border-radius: 6px; padding: 8px; }",
        ".fi-card img { height: 96px; border-radius: 4px; object-fit: cover; }",
        ".fi-pics { display: flex; gap: 6px; margin-bottom: 6px; }",
        ".fi-times button { padding: 0 3px; font-size: .78em; }",
        ".fi-maybe { outline: 1px dashed #f59e0b; }",
        ".fi-pick { position: relative; } .fi-pick ul { position: absolute; z-index: 5; left: 0; right: 0; background: #30404d; list-style: none; margin: 0; padding: 0; max-height: 14em; overflow-y: auto; }",
        ".fi-pick li { padding: 3px 6px; cursor: pointer; } .fi-pick li:hover { background: #3b82f6; }",
      ].join("\n") }));
    }
    return { body, footer, close };
  }

  async function sceneOf(id) {
    return (await gql("query($id: ID!) { findScene(id: $id) { id performers { id name } } }", { id })).findScene;
  }

  async function addToScene(id, performerId) {
    const scene = await sceneOf(id);
    const ids = [...new Set([...(scene.performers || []).map((p) => String(p.id)), String(performerId)])];
    await gql("mutation($i: SceneUpdateInput!) { sceneUpdate(input: $i) { id } }", { i: { id, performer_ids: ids } });
  }

  // a performer to pick: type, choose
  function performerPicker(onPick) {
    const input = el("input", { type: "text", className: "form-control form-control-sm", placeholder: "Who is it? (name)" });
    const list = el("ul", {});
    let timer = null;
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = input.value.trim();
        if (q.length < 2) { list.replaceChildren(); return; }
        const found = (await gql("query($q: String!) { findPerformers(filter: { q: $q, per_page: 8 }) { performers { id name disambiguation } } }", { q })).findPerformers.performers;
        list.replaceChildren(...found.map((p) => el("li", { textContent: p.name + (p.disambiguation ? ` (${p.disambiguation})` : ""),
          onclick: () => { input.value = p.name; list.replaceChildren(); onPick(p); } })));
      }, 250);
    });
    return el("div", { className: "fi-pick" }, input, list);
  }

  function times(list) {
    return el("div", { className: "fi-times small" }, ...list.slice(0, 8).map((t) =>
      el("button", { type: "button", className: "btn btn-link", textContent: clock(t), title: "Play from here", onclick: () => seek(t) })),
      list.length > 8 ? ` +${list.length - 8}` : "");
  }

  function render(d, id, result) {
    const note = el("div", { className: "small mb-2", style: { minHeight: "1.3em" } });
    const say = (text, bad) => { note.className = `small mb-2 ${bad ? "text-danger" : "text-success"}`; note.textContent = text; };
    const parts = [el("p", { className: "small text-muted", textContent:
      `${result.faces} face${result.faces === 1 ? "" : "s"} in ${result.frames} frames of the video, compared with the ${result.known_performers} performer${result.known_performers === 1 ? "" : "s"} known by face (from their portraits and the faces confirmed here).` }), note];
    if (!result.known_performers) {
      parts.push(el("div", { className: "alert alert-warning small", textContent:
        "No performer is known by face yet — run Settings → Tasks → Face Identifier → Learn the performers' faces (it reads their portraits)." }));
    }
    // recognised
    const found = result.found || [];
    parts.push(el("h6", { textContent: found.length ? "Recognised" : "Nobody recognised" }));
    if (found.length) {
      parts.push(el("div", { className: "fi-grid mb-3" }, ...found.map((h) => {
        const action = el("div", { className: "d-flex flex-wrap", style: { gap: "6px" } });
        const add = async (confirmToo) => {
          try {
            if (!h.in_scene) await addToScene(id, h.performer_id);
            if (confirmToo) await run({ mode: "confirm", scene_id: id, performer_id: h.performer_id, faces: h.faces.join(",") });
            h.in_scene = true;
            action.replaceChildren(el("span", { className: "small text-success", textContent: confirmToo ? "✓ in the scene — and learnt" : "✓ in the scene" }));
          } catch (err) { say(String(err.message || err), true); }
        };
        if (h.in_scene) action.append(el("span", { className: "small text-success", textContent: "✓ in the scene" }));
        else if (h.sure) action.append(el("button", { type: "button", className: "btn btn-primary btn-sm", textContent: "Add to scene", onclick: () => add(false) }));
        if (!h.sure) {
          action.append(el("button", { type: "button", className: "btn btn-primary btn-sm", textContent: "Yes, that's them", onclick: () => add(true) }),
            el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "No", onclick: (e) => { e.target.closest(".fi-card").remove(); } }));
        }
        return el("div", { className: `fi-card ${h.sure ? "" : "fi-maybe"}` },
          el("div", { className: "fi-pics" },
            h.crop ? el("img", { src: h.crop, title: "in the video" }) : "",
            el("img", { src: `/performer/${h.performer_id}/image`, title: "their portrait" })),
          el("div", {}, el("a", { href: `/performers/${h.performer_id}`, target: "_blank", textContent: h.name })),
          el("div", { className: "small text-muted", textContent:
            `${h.sure ? "" : "maybe — "}seen in ${h.count} frame${h.count === 1 ? "" : "s"} · ${Math.round(h.best * 100)} % alike` }),
          times(h.times || []), action);
      })));
    }
    // not recognised
    const unknown = result.unknown || [];
    if (unknown.length) {
      parts.push(el("h6", { textContent: "Not recognised" }),
        el("p", { className: "small text-muted", textContent: "The same person's faces together. Say who it is: added to the scene, and learnt — next time they're recognised." }),
        el("div", { className: "fi-grid mb-3" }, ...unknown.map((g) => {
          const action = el("div", {});
          let picked = null;
          const addBox = el("input", { type: "checkbox", checked: true });
          const confirmButton = el("button", { type: "button", className: "btn btn-primary btn-sm mt-1", textContent: "That's them", disabled: true,
            onclick: async () => {
              try {
                await run({ mode: "confirm", scene_id: id, performer_id: picked.id, faces: g.faces.join(",") });
                if (addBox.checked) await addToScene(id, picked.id);
                action.replaceChildren(el("span", { className: "small text-success", textContent: `✓ ${picked.name} — learnt${addBox.checked ? ", in the scene" : ""}` }));
              } catch (err) { say(String(err.message || err), true); }
            } });
          action.append(performerPicker((p) => { picked = p; confirmButton.disabled = false; }),
            el("label", { className: "small mb-0 mr-2" }, addBox, " add to the scene"), confirmButton);
          return el("div", { className: "fi-card" },
            el("div", { className: "fi-pics" }, g.crop ? el("img", { src: g.crop }) : ""),
            el("div", { className: "small text-muted", textContent: `seen in ${g.count} frame${g.count === 1 ? "" : "s"}` }),
            times(g.times || []), action);
        })));
    }
    // Visage
    const visageBox = el("div", {});
    const visageButton = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Ask Visage too",
      title: "Visage's face search (cc1234, Hugging Face) on the scene's preview sprite — it knows StashDB's and JavStash's performers only",
      onclick: async () => {
        visageButton.disabled = true;
        visageBox.replaceChildren(el("p", { className: "small", textContent: "Asking Visage … (sends the scene's preview sprite to the Visage service)" }));
        try {
          const v = await run({ mode: "visage", scene_id: id });
          visageBox.replaceChildren(
            v.note ? el("p", { className: "small text-muted", textContent: v.note }) : "",
            el("div", { className: "fi-grid" }, ...(v.matches || []).map((m) => el("div", { className: "fi-card" },
              m.image ? el("div", { className: "fi-pics" }, el("img", { src: m.image })) : "",
              el("div", {}, m.url ? el("a", { href: m.url, target: "_blank", rel: "noopener noreferrer", textContent: m.name }) : m.name),
              el("div", { className: "small text-muted", textContent: `${Math.round(m.confidence)} % · ${m.source || "Visage"}${m.hits ? ` · ${m.hits} frame${m.hits === 1 ? "" : "s"}` : ""}` }),
              m.in_stash
                ? el("button", { type: "button", className: "btn btn-primary btn-sm mt-1", textContent: `Add ${m.in_stash.name} to scene`,
                  onclick: async (e) => { await addToScene(id, m.in_stash.id); e.target.replaceWith(el("span", { className: "small text-success", textContent: "✓ in the scene" })); } })
                : el("div", { className: "small text-muted", textContent: "not in your library" })))));
        } catch (err) {
          visageBox.replaceChildren(el("div", { className: "alert alert-danger small", textContent: String(err.message || err) }));
        }
        visageButton.disabled = false;
      } });
    parts.push(el("h6", { className: "mt-2", textContent: "Visage" }),
      el("p", { className: "small text-muted mb-1", textContent: "A second opinion from Visage's face database — StashDB's and JavStash's performers only (for concert recordings it rarely knows anyone)." }),
      visageButton, visageBox);
    d.body.replaceChildren(...parts);
  }

  async function open() {
    const id = sceneId();
    if (!id) return;
    const d = dialog("Who's in this scene?");
    const status = el("p", { textContent: "Starting …" });
    const bar = el("div", { className: "progress", style: { height: "8px" } }, el("div", { className: "progress-bar", style: { width: "0%" } }));
    d.body.replaceChildren(status, bar);
    const again = el("button", { type: "button", className: "btn btn-secondary mr-auto", textContent: "Look again",
      title: "The video looked at again (e.g. after learning more faces)", onclick: () => go(true) });
    const learn = el("button", { type: "button", className: "btn btn-secondary", textContent: "Learn the performers' faces",
      title: "Read every performer's portrait again (a task in Settings → Tasks)", onclick: async () => {
        await gql("mutation($p: ID!, $d: String, $a: Map) { runPluginTask(plugin_id: $p, description: $d, args_map: $a) }",
          { p: PLUGIN_ID, d: "Learn the performers' faces", a: { mode: "learn" } });
        learn.textContent = "Learning — a task (Settings → Tasks)";
        learn.disabled = true;
      } });
    d.footer.prepend(again, learn);
    const go = async (fresh) => {
      d.body.replaceChildren(status, bar);
      status.textContent = "Starting …";
      let r;
      try { r = await run({ mode: "start", scene_id: id, again: fresh ? "true" : "" }); }
      catch (err) { d.body.replaceChildren(el("div", { className: "alert alert-danger", style: { whiteSpace: "pre-wrap" }, textContent: String(err.message || err) })); return; }
      if (!r.running) { render(d, id, r); return; }
      // a Stash task: follow it
      const began = Date.now();
      const poll = async () => {
        if (!status.isConnected) return;
        let job = null, p = null;
        try {
          [job, p] = await Promise.all([
            gql("query($id: ID!) { findJob(input: { id: $id }) { status error } }", { id: String(r.job) }).then((x) => x.findJob),
            run({ mode: "status", scene_id: id })]);
        } catch (e) { /* again */ }
        const s = Math.round((Date.now() - began) / 1000);
        if (job && ["FAILED", "CANCELLED"].includes(job.status)) {
          status.textContent = job.status === "CANCELLED" ? "The task was stopped." : `The task failed: ${job.error || ""}`;
          return;
        }
        if ((!job || job.status === "FINISHED") && p && p.phase === "done") { go(false); return; }
        if (job && job.status === "READY") status.textContent = `Waiting in Stash's task queue … ${clock(s)}`;
        else if (p && p.total) {
          status.textContent = `Looking at the video: frame ${p.done} of ${p.total} … ${clock(s)}`;
          bar.firstChild.style.width = `${Math.round((100 * p.done) / p.total)}%`;
        } else status.textContent = `Starting (the first time: downloading the face models, 40 MB) … ${clock(s)}`;
        setTimeout(poll, 3000);
      };
      status.textContent = "Runs as a Stash task — closing this dialog doesn't stop it.";
      setTimeout(poll, 1500);
    };
    go(false);
  }

  // -- the entry in the scene's ⋮ menu ---------------------------------------------------------------
  function addToMenu() {
    const id = sceneId();
    const toggle = id && document.getElementById("operation-menu");
    if (!toggle) return;
    const menu = document.querySelector('[aria-labelledby="operation-menu"]') ||
      (toggle.parentElement && toggle.parentElement.querySelector(".dropdown-menu"));
    if (!menu || menu.querySelector("#face-identifier-item")) return;
    menu.append(el("button", { id: "face-identifier-item", type: "button", className: "dropdown-item", textContent: "Who's in this scene?",
      onclick: () => { if (menu.classList.contains("show")) toggle.click(); open(); } }));
  }
  new MutationObserver(() => { try { addToMenu(); } catch (e) { /* never into Stash's page */ } })
    .observe(document.body, { childList: true, subtree: true });
})();
