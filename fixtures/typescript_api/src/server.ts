import { createServer } from "node:http";

export function makeServer() {
  const items = new Map<string, string>();
  return createServer((request, response) => {
    response.setHeader("content-type", "application/json");
    if (request.headers.authorization !== "Bearer fixture-token") {
      response.writeHead(401).end(JSON.stringify({ error: "unauthorized" }));
      return;
    }
    if (request.method === "POST" && request.url === "/items") {
      let body = "";
      request.on("data", chunk => { body += chunk; });
      request.on("end", () => {
        try {
          const input = JSON.parse(body);
          if (typeof input.value !== "string" || !input.value.trim()) throw new Error("value");
          items.set("1", input.value);
          response.writeHead(201).end(JSON.stringify({ id: "1", value: input.value }));
        } catch {
          response.writeHead(422).end(JSON.stringify({ error: "invalid input" }));
        }
      });
      return;
    }
    if (request.method === "GET" && request.url === "/items/1" && items.has("1")) {
      response.end(JSON.stringify({ id: "1", value: items.get("1") }));
      return;
    }
    response.writeHead(404).end(JSON.stringify({ error: "not found" }));
  });
}
