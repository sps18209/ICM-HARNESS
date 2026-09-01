const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");
const { spawn, spawnSync } = require("node:child_process");
const { HarnessClient } = require("../out/api");

// End-to-end test against a real `icm serve`. Configure the interpreter with
// ICM_TEST_PYTHON and, for a source checkout, ICM_TEST_PYTHONPATH.
const PYTHON = process.env.ICM_TEST_PYTHON || "python3";
const PYTHONPATH = process.env.ICM_TEST_PYTHONPATH;

function harnessImportable() {
  const env = { ...process.env };
  if (PYTHONPATH) {
    env.PYTHONPATH = PYTHONPATH;
  }
  const res = spawnSync(PYTHON, ["-c", "import icm_harness"], { env });
  return res.status === 0;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
    srv.on("error", reject);
  });
}

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, attempts, gap) {
  for (let i = 0; i < attempts; i++) {
    if (await fn()) {
      return true;
    }
    await delay(gap);
  }
  return false;
}

const available = harnessImportable();

test(
  "full round lifecycle over the operator API",
  { skip: available ? false : "icm_harness not importable by ICM_TEST_PYTHON" },
  async (t) => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "icm-int-"));
    const port = await freePort();
    const env = { ...process.env };
    if (PYTHONPATH) {
      env.PYTHONPATH = PYTHONPATH;
    }

    spawnSync(PYTHON, ["-m", "icm_harness", "init", root], { env });
    const server = spawn(
      PYTHON,
      ["-m", "icm_harness", "serve", "--host", "127.0.0.1", "--port", String(port)],
      { cwd: root, env },
    );
    t.after(() => server.kill());
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));

    const client = new HarnessClient({ host: "127.0.0.1", port, token: "" });
    const up = await waitFor(() => client.health(), 40, 250);
    assert.ok(up, "server became healthy");

    await t.test("create + run reaches closed with artifacts and events", async () => {
      const round = await client.createRound({
        objective: "integration lifecycle",
        intent: "build",
        run: true,
        dry_run: true,
      });
      assert.match(round.round_id, /^r-/);
      const closed = await waitFor(
        async () => (await client.getRound(round.round_id)).status === "closed",
        40,
        250,
      );
      assert.ok(closed, "round closed");
      const detail = await client.getRound(round.round_id);
      assert.ok(detail.artifacts.length > 0, "produced artifacts");
      assert.ok(detail.events.length > 0, "recorded events");
      const first = await client.artifact(detail.artifacts[0].id);
      assert.ok(first.content.length > 0, "artifact has content");
    });

    await t.test("decide-mode round pauses at the human gate, then approves", async () => {
      const round = await client.createRound({
        objective: "integration gate",
        intent: "decide",
        run: true,
        dry_run: true,
      });
      const waited = await waitFor(
        async () => (await client.getRound(round.round_id)).status === "waiting_approval",
        40,
        250,
      );
      assert.ok(waited, "reached the human gate");
      const gated = await client.getRound(round.round_id);
      assert.ok(gated.active_gate, "an active gate is set");
      await client.approveRound(round.round_id, true, true);
      const closed = await waitFor(
        async () => (await client.getRound(round.round_id)).status === "closed",
        40,
        250,
      );
      assert.ok(closed, "closed after approval");
    });

    await t.test("cancel then retry re-enters the workspace (lease released)", async () => {
      const round = await client.createRound({
        objective: "integration cancel-retry",
        intent: "quick",
        run: false,
        dry_run: true,
      });
      const cancelled = await client.cancelRound(round.round_id);
      assert.strictEqual(cancelled.status, "cancelled");
      await client.retryRound(round.round_id, true, true);
      const closed = await waitFor(
        async () => (await client.getRound(round.round_id)).status === "closed",
        40,
        250,
      );
      assert.ok(closed, "retry ran to completion");
    });
  },
);
