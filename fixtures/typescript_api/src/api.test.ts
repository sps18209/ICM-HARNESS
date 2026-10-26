import { strict as assert } from "node:assert";
import { once } from "node:events";
import { AddressInfo } from "node:net";
import { test } from "node:test";
import { makeServer } from "./server";

async function withServer(run: (base: string) => Promise<void>) {
  const server = makeServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  try {
    await run(base);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
}

test("reject unauthorized write", async () => withServer(async base => {
  const response = await fetch(`${base}/items`, { method: "POST", body: '{"value":"x"}' });
  assert.equal(response.status, 401);
}));

test("create and read item", async () => withServer(async base => {
  const headers = { authorization: "Bearer fixture-token", "content-type": "application/json" };
  const created = await fetch(`${base}/items`, {
    method: "POST", headers, body: JSON.stringify({ value: "saved" }),
  });
  assert.equal(created.status, 201);
  const response = await fetch(`${base}/items/1`, { headers });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { id: "1", value: "saved" });
}));

test("reject invalid input", async () => withServer(async base => {
  const response = await fetch(`${base}/items`, {
    method: "POST", headers: { authorization: "Bearer fixture-token" }, body: "{}",
  });
  assert.equal(response.status, 422);
}));
