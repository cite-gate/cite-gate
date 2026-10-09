import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { MAX_PROSE_CHARS, PRIVACY } from "../src/index.js";

const SOURCE = "The harbour held 1,200 ships in 1850. A lighthouse stood on the eastern pier.";
const URL_MCP = "https://cite-gate.example.workers.dev/mcp";

function post(body, headers = {}) {
  return new Request(URL_MCP, { method: "POST", headers: { "content-type": "application/json", ...headers }, body: JSON.stringify(body) });
}

function mockEnv() {
  const points = [];
  return { env: { SALT: "test-salt", LOG: { writeDataPoint: (p) => points.push(p) } }, points };
}

const call = (name, args, id = 1) => ({ jsonrpc: "2.0", id, method: "tools/call", params: { name, arguments: args } });

test("root page shows the privacy text", async () => {
  const r = await worker.fetch(new Request("https://x.workers.dev/"), {});
  assert.equal(r.status, 200);
  assert.ok((await r.text()).includes(PRIVACY));
});

test("initialize, list, and a passing + failing check", async () => {
  const { env } = mockEnv();
  let r = await worker.fetch(post({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", clientInfo: { name: "test-client", version: "1" } } }), env);
  assert.equal((await r.json()).result.serverInfo.name, "cite-gate");
  r = await worker.fetch(post({ jsonrpc: "2.0", id: 2, method: "tools/list" }), env);
  assert.deepEqual((await r.json()).result.tools.map((t) => t.name), ["check_citations", "check_numbers"]);
  const claims = { sections: [{ items: [
    { id: "ok", text: "The harbour had room for 1,200 ships by 1850.", claims: [{ src: "town", quote: "The harbour held 1,200 ships in 1850." }] },
    { id: "bad", text: "It held 1,500 ships.", claims: [{ src: "town", quote: "The harbour held 1,200 ships in 1850." }] },
  ] }] };
  r = await worker.fetch(post(call("check_citations", { claims, sources: { town: SOURCE } })), env);
  const body = JSON.parse((await r.json()).result.content[0].text);
  assert.equal(body.passed, false);
  assert.deepEqual(body.failures.map((f) => f.item), ["bad"]);
  assert.ok(body.note.includes("discussions/1"));
});

test("prose over the hosted limit is a tool error, not a crash", async () => {
  const big = "word ".repeat(Math.ceil(MAX_PROSE_CHARS / 5) + 10);
  const claims = { sections: [{ items: [{ id: "x", text: big, claims: [{ src: "town", quote: "The harbour held 1,200 ships in 1850." }] }] }] };
  const r = await worker.fetch(post(call("check_citations", { claims, sources: { town: SOURCE } })), {});
  const res = (await r.json()).result;
  assert.equal(res.isError, true);
  assert.ok(res.content[0].text.includes("local server"));
});

test("notifications get 202, bad JSON gets 400, GET /mcp gets 405", async () => {
  assert.equal((await worker.fetch(post({ jsonrpc: "2.0", method: "notifications/initialized" }), {})).status, 202);
  const bad = new Request(URL_MCP, { method: "POST", body: "not json" });
  assert.equal((await worker.fetch(bad, {})).status, 400);
  assert.equal((await worker.fetch(new Request(URL_MCP), {})).status, 405);
});

test("logs carry no script text and mark bots and self calls", async () => {
  const { env, points } = mockEnv();
  const secret = "UNIQUE-SCRIPT-TEXT-1850";
  const claims = { sections: [{ items: [{ id: "i", text: `${secret} ships.`, claims: [{ src: "town", quote: "The harbour held 1,200 ships in 1850." }] }] }] };
  await worker.fetch(post(call("check_citations", { claims, sources: { town: SOURCE } }), { "cf-connecting-ip": "203.0.113.7", "user-agent": "claude-code/2.0" }), env);
  await worker.fetch(post(call("check_numbers", { text: "1850", quotes: ["1850 here"] }), { "user-agent": "curl/8" }), env);
  await worker.fetch(post(call("check_numbers", { text: "1850", quotes: ["1850 here"] }), { "x-cite-gate-self": "1" }), env);
  assert.equal(points.length, 3);
  const dump = JSON.stringify(points);
  assert.ok(!dump.includes(secret) && !dump.includes("203.0.113.7") && !dump.includes("harbour"));
  assert.deepEqual(points.map((p) => p.blobs[2]), ["user", "bot", "self"]);
  assert.match(points[0].blobs[3], /^[0-9a-f]{12}$/);
});

test("CPU: a full-size hosted call stays small", async () => {
  // ~3,000 characters of prose, 25 items, realistic quotes
  const quote = "The harbour held 1,200 ships in 1850. A lighthouse stood on the eastern pier.";
  const items = Array.from({ length: 25 }, (_, i) => ({ id: String(i), text: "In 1850 the harbour held 1,200 ships and a lighthouse stood there. ".repeat(2).slice(0, 118), claims: [{ src: "town", quote }] }));
  const claims = { sections: [{ items }] };
  const t = process.cpuUsage();
  for (let k = 0; k < 20; k++) await worker.fetch(post(call("check_citations", { claims, sources: { town: SOURCE } })), {});
  const ms = (process.cpuUsage(t).user + process.cpuUsage(t).system) / 1000 / 20;
  console.log(`cpu per full-size call: ${ms.toFixed(2)} ms`);
  assert.ok(ms < 50);
});
