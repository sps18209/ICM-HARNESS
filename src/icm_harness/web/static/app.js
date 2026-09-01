"use strict";

const state = { rounds: [], selectedId: null, detail: null, polling: null };
const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed: ${response.status}`);
  return payload;
}

function node(tag, options = {}, children = []) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = String(options.text);
  if (options.type) element.type = options.type;
  for (const [key, value] of Object.entries(options.attrs || {})) element.setAttribute(key, value);
  for (const child of children) element.append(child);
  return element;
}

function humanize(value) {
  return String(value || "").replaceAll("_", " ").replaceAll(".", " · ");
}

function relativeTime(value) {
  const date = new Date(value);
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const format = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(seconds) < 60) return format.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return format.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return format.format(hours, "hour");
  return format.format(Math.round(hours / 24), "day");
}

function setConnection(online) {
  const element = $("connection-status");
  element.textContent = online ? "Live" : "Reconnecting";
  element.className = `connection ${online ? "online" : "offline"}`;
}

function toast(message) {
  const element = $("toast");
  element.textContent = message;
  element.hidden = false;
  window.setTimeout(() => { element.hidden = true; }, 3200);
}

async function refreshRounds({ preserveSelection = true } = {}) {
  try {
    state.rounds = await api("/api/rounds");
    setConnection(true);
    if (!preserveSelection || !state.selectedId) state.selectedId = state.rounds[0]?.round_id || null;
    renderRoundList();
    if (state.selectedId) await loadRound(state.selectedId, { quiet: true });
    else renderEmpty();
  } catch (error) {
    setConnection(false);
    if (!preserveSelection) toast(error.message);
  }
}

function renderRoundList() {
  const list = $("round-list");
  list.replaceChildren();
  for (const round of state.rounds) {
    const button = node("button", {
      className: "round-card",
      type: "button",
      attrs: { "aria-current": round.round_id === state.selectedId ? "true" : "false" },
    }, [
      node("span", { text: humanize(round.status) }),
      node("strong", { text: round.objective }),
      node("span", { text: `${round.current_stage || "complete"} · ${relativeTime(round.updated_at)}` }),
    ]);
    button.addEventListener("click", () => loadRound(round.round_id));
    list.append(button);
  }
}

function renderEmpty() {
  $("empty-state").hidden = false;
  $("round-detail").hidden = true;
}

async function loadRound(roundId, { quiet = false } = {}) {
  try {
    state.selectedId = roundId;
    state.detail = await api(`/api/rounds/${encodeURIComponent(roundId)}`);
    renderRoundList();
    renderDetail();
  } catch (error) {
    if (!quiet) toast(error.message);
  }
}

function renderDetail() {
  const round = state.detail;
  if (!round) return renderEmpty();
  $("empty-state").hidden = true;
  $("round-detail").hidden = false;
  $("round-status").textContent = humanize(round.status);
  $("round-status").dataset.status = round.status;
  $("round-id").textContent = round.round_id;
  $("round-objective").textContent = round.objective;
  $("round-reason").textContent = round.last_error || round.route_reason || "";
  $("progress-label").textContent = `${Math.min(round.cursor, round.stages.length)} of ${round.stages.length} stages`;
  renderActions(round);
  renderStages(round);
  renderWorkspaceChanges(round);
  renderArtifacts(round.artifacts || []);
  renderEvents(round.events || []);
}

function actionButton(label, action, className = "secondary", body = {}) {
  const button = node("button", { text: label, type: "button", className });
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await api(`/api/rounds/${encodeURIComponent(state.selectedId)}/${action}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      toast(`${label} requested`);
      await window.setTimeout(() => loadRound(state.selectedId, { quiet: true }), 250);
    } catch (error) {
      toast(error.message);
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function renderActions(round) {
  const actions = $("round-actions");
  actions.replaceChildren();
  if (["active"].includes(round.status)) actions.append(actionButton("Run", "run", "primary"));
  if (round.status === "waiting_approval") actions.append(actionButton("Approve and continue", "approve", "primary", { run: true }));
  if (["failed", "blocked", "cancelled"].includes(round.status)) actions.append(actionButton("Retry", "retry", "primary", { run: true }));
  if (["active", "running", "waiting_approval", "blocked"].includes(round.status)) actions.append(actionButton("Cancel", "cancel", "danger"));
  if (round.status === "closed" && round.workspace_path && !round.promoted) {
    const promote = actionButton("Promote to base", "promote", "primary");
    promote.addEventListener("click", (event) => {
      if (!window.confirm("Merge this round's isolated worktree into the base branch?")) {
        event.stopImmediatePropagation();
      }
    }, {capture: true});
    actions.append(promote);
  }
}

function renderStages(round) {
  const list = $("stage-list");
  list.replaceChildren();
  round.stages.forEach((stage, index) => {
    const classNames = ["stage-item"];
    if (index < round.cursor) classNames.push("complete");
    if (stage === round.current_stage) classNames.push("current");
    list.append(node("li", { className: classNames.join(" ") }, [
      node("span", { className: "stage-index", text: index < round.cursor ? "Complete" : stage === round.current_stage ? "Current" : `Stage ${index + 1}` }),
      node("strong", { text: humanize(stage) }),
    ]));
  });
}

function renderWorkspaceChanges(round) {
  const panel = $("changes-panel");
  const content = round.workspace_diff || "";
  panel.hidden = !content;
  $("workspace-diff").textContent = content;
}

function renderArtifacts(artifacts) {
  $("artifact-count").textContent = artifacts.length;
  const list = $("artifact-list");
  list.replaceChildren();
  if (!artifacts.length) {
    list.append(node("p", { className: "muted", text: "Artifacts appear here as stages finish." }));
    return;
  }
  for (const artifact of artifacts) {
    const button = node("button", { className: "artifact-button", type: "button" }, [
      node("strong", { text: artifact.name }),
      node("span", { text: `${humanize(artifact.stage_ref)} · ${artifact.size.toLocaleString()} bytes` }),
    ]);
    button.addEventListener("click", () => openArtifact(artifact.id));
    list.append(button);
  }
}

function eventDetail(event) {
  const payload = event.payload || {};
  return payload.summary || payload.error || payload.message || payload.model || payload.reason || "";
}

function renderEvents(events) {
  $("event-count").textContent = events.length;
  const list = $("event-list");
  list.replaceChildren();
  for (const event of [...events].reverse()) {
    list.append(node("li", { className: "event-item" }, [
      node("span", { className: "event-dot", attrs: { "aria-hidden": "true" } }),
      node("div", {}, [
        node("strong", { text: `${humanize(event.kind)} · ${event.stage_ref ? humanize(event.stage_ref) : "round"}` }),
        node("p", { text: [eventDetail(event), relativeTime(event.created_at)].filter(Boolean).join(" · ") }),
      ]),
    ]));
  }
}

async function openArtifact(artifactId) {
  try {
    const artifact = await api(`/api/artifacts/${artifactId}`);
    $("artifact-title").textContent = artifact.name;
    $("artifact-stage").textContent = humanize(artifact.stage_ref);
    renderTextArtifact($("artifact-content"), artifact.content, artifact.name);
    $("artifact-dialog").showModal();
  } catch (error) {
    toast(error.message);
  }
}

function renderTextArtifact(container, content, name) {
  container.replaceChildren();
  if (name.endsWith(".json")) {
    try { content = JSON.stringify(JSON.parse(content), null, 2); } catch (_) { /* show source */ }
    container.append(node("pre", {}, [node("code", { text: content })]));
    return;
  }
  let inCode = false;
  let codeLines = [];
  const flushCode = () => {
    if (!codeLines.length) return;
    container.append(node("pre", {}, [node("code", { text: codeLines.join("\n") })]));
    codeLines = [];
  };
  for (const line of content.split("\n")) {
    if (line.startsWith("```")) {
      if (inCode) flushCode();
      inCode = !inCode;
      continue;
    }
    if (inCode) { codeLines.push(line); continue; }
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (heading) {
      container.append(node(`h${heading[1].length}`, { text: heading[2] }));
    } else if (line.startsWith("- ")) {
      container.append(node("li", { text: line.slice(2) }));
    } else if (line.trim()) {
      container.append(node("p", { text: line }));
    }
  }
  flushCode();
}

function openNewDialog() {
  $("form-error").textContent = "";
  $("new-round-dialog").showModal();
  $("new-round-form").elements.objective.focus();
}

async function submitNewRound(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const payload = {
    objective: data.get("objective"),
    intent: data.get("intent"),
    clarity: Number(data.get("clarity")),
    uncertainty: Number(data.get("uncertainty")),
    stakes: Number(data.get("stakes")),
    reversibility: Number(data.get("reversibility")),
    production_change: data.get("production_change") === "on",
    dry_run: data.get("dry_run") === "on",
    run: true,
  };
  const submit = form.querySelector("button[type=submit]");
  submit.disabled = true;
  try {
    const round = await api("/api/rounds", { method: "POST", body: JSON.stringify(payload) });
    state.selectedId = round.round_id;
    form.reset();
    $("new-round-dialog").close();
    await refreshRounds();
  } catch (error) {
    $("form-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
}

function bind() {
  $("new-round-button").addEventListener("click", openNewDialog);
  $("empty-new-button").addEventListener("click", openNewDialog);
  $("refresh-button").addEventListener("click", () => refreshRounds({ preserveSelection: true }));
  $("close-dialog-button").addEventListener("click", () => $("new-round-dialog").close());
  $("cancel-dialog-button").addEventListener("click", () => $("new-round-dialog").close());
  $("close-artifact-button").addEventListener("click", () => $("artifact-dialog").close());
  $("new-round-form").addEventListener("submit", submitNewRound);
}

bind();
refreshRounds({ preserveSelection: false });
state.polling = window.setInterval(() => refreshRounds({ preserveSelection: true }), 1500);
