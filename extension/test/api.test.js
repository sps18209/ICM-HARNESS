const test = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const { HarnessClient, HarnessApiError } = require("../out/api");

// Spin up a mock harness API that records the last request and returns a
// scripted response, so we can assert exactly what HarnessClient sends.
function mockServer(handler) {
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const body = Buffer.concat(chunks).toString("utf-8");
      handler(req, body, res);
    });
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, port });
    });
  });
}

function clientFor(port, token = "") {
  return new HarnessClient({ host: "127.0.0.1", port, token });
}

function reply(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(body);
}

test("listRounds issues GET /api/rounds and parses the array", async () => {
  let seen;
  const { server, port } = await mockServer((req, _body, res) => {
    seen = { method: req.method, url: req.url };
    reply(res, 200, [{ round_id: "r-1" }]);
  });
  try {
    const rounds = await clientFor(port).listRounds();
    assert.deepStrictEqual(seen, { method: "GET", url: "/api/rounds" });
    assert.strictEqual(rounds[0].round_id, "r-1");
  } finally {
    server.close();
  }
});

test("createRound POSTs the JSON body", async () => {
  let seen;
  const { server, port } = await mockServer((req, body, res) => {
    seen = { method: req.method, url: req.url, ct: req.headers["content-type"], body };
    reply(res, 201, { round_id: "r-9", status: "active" });
  });
  try {
    const round = await clientFor(port).createRound({
      objective: "do it",
      intent: "build",
      run: true,
      dry_run: true,
    });
    assert.strictEqual(seen.method, "POST");
    assert.strictEqual(seen.url, "/api/rounds");
    assert.strictEqual(seen.ct, "application/json");
    assert.deepStrictEqual(JSON.parse(seen.body), {
      objective: "do it",
      intent: "build",
      run: true,
      dry_run: true,
    });
    assert.strictEqual(round.round_id, "r-9");
  } finally {
    server.close();
  }
});

test("events encodes the after query parameter", async () => {
  let url;
  const { server, port } = await mockServer((req, _body, res) => {
    url = req.url;
    reply(res, 200, []);
  });
  try {
    await clientFor(port).events("r 1", 42);
    assert.strictEqual(url, "/api/rounds/r%201/events?after=42");
  } finally {
    server.close();
  }
});

test("bearer token is sent only when configured", async () => {
  let auth;
  const { server, port } = await mockServer((req, _body, res) => {
    auth = req.headers["authorization"];
    reply(res, 200, { status: "ok" });
  });
  try {
    await clientFor(port, "sekret").health();
    assert.strictEqual(auth, "Bearer sekret");
    await clientFor(port).health();
    assert.strictEqual(auth, undefined);
  } finally {
    server.close();
  }
});

test("non-2xx maps to HarnessApiError with the server error message", async () => {
  const { server, port } = await mockServer((_req, _body, res) => {
    reply(res, 400, { error: "ValueError: objective is required" });
  });
  try {
    await assert.rejects(
      () => clientFor(port).createRound({ objective: "" }),
      (err) => {
        assert.ok(err instanceof HarnessApiError);
        assert.strictEqual(err.status, 400);
        assert.match(err.message, /objective is required/);
        return true;
      },
    );
  } finally {
    server.close();
  }
});

test("health returns false when the server is down", async () => {
  // Nothing listening on this port.
  const ok = await new HarnessClient({ host: "127.0.0.1", port: 9, token: "" }).health();
  assert.strictEqual(ok, false);
});

test("diff unwraps the content field", async () => {
  const { server, port } = await mockServer((_req, _body, res) => {
    reply(res, 200, { content: "diff --git a b" });
  });
  try {
    assert.strictEqual(await clientFor(port).diff("r-1"), "diff --git a b");
  } finally {
    server.close();
  }
});
