const test = require("node:test");
const assert = require("node:assert");
const { stageState, statusIcon, languageFor, truncateObjective } = require("../out/logic");

function round(overrides) {
  return {
    round_id: "r-1",
    objective: "x",
    route: [],
    stages: ["a", "b", "c"],
    cursor: 1,
    status: "running",
    version: 1,
    created_at: "",
    updated_at: "",
    route_reason: "",
    cancel_requested: false,
    current_stage: "b",
    active_gate: null,
    ...overrides,
  };
}

test("statusIcon maps known and unknown statuses", () => {
  assert.strictEqual(statusIcon("closed"), "pass-filled");
  assert.strictEqual(statusIcon("waiting_approval"), "person");
  assert.strictEqual(statusIcon("nonsense"), "circle-outline");
});

test("stageState: done before cursor, current at cursor, pending after", () => {
  const r = round({ cursor: 1, status: "active" });
  assert.strictEqual(stageState(r, "a", 0).label, "done");
  assert.strictEqual(stageState(r, "b", 1).label, "current");
  assert.strictEqual(stageState(r, "c", 2).label, "pending");
});

test("stageState: closed round marks every stage done", () => {
  const r = round({ status: "closed", cursor: 3 });
  assert.strictEqual(stageState(r, "a", 0).label, "done");
  assert.strictEqual(stageState(r, "c", 2).label, "done");
});

test("stageState: awaiting approval only for the active gate stage", () => {
  const r = round({ status: "waiting_approval", cursor: 1, active_gate: "b" });
  assert.strictEqual(stageState(r, "b", 1).label, "awaiting approval");
  assert.strictEqual(stageState(r, "b", 1).icon, "person");
});

test("stageState: running/failed reflected at cursor", () => {
  assert.strictEqual(stageState(round({ status: "running", cursor: 1 }), "b", 1).label, "running");
  assert.strictEqual(stageState(round({ status: "failed", cursor: 1 }), "b", 1).label, "failed");
});

test("languageFor picks by extension then media type", () => {
  assert.strictEqual(languageFor("frame.md", "text/plain"), "markdown");
  assert.strictEqual(languageFor("result.json", "text/plain"), "json");
  assert.strictEqual(languageFor("x", "application/json"), "json");
  assert.strictEqual(languageFor("change.diff", ""), "diff");
  assert.strictEqual(languageFor("notes.txt", "text/plain"), "plaintext");
});

test("truncateObjective adds ellipsis past the limit", () => {
  assert.strictEqual(truncateObjective("short", 60), "short");
  const long = "a".repeat(80);
  const out = truncateObjective(long, 60);
  assert.strictEqual(out.length, 60);
  assert.ok(out.endsWith("…"));
});
