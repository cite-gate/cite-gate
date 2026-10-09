// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 MLPC Inc.
//
// Hosted cite-gate MCP endpoint (Cloudflare Workers, Streamable HTTP, JSON responses only).
//
// What is logged per call (and nothing else): minute, tool name, pass/fail counts, the client
// name/version from MCP `initialize`, a bot/self flag, and a daily-rotating hash of the IP.
// Script text, quotes and sources are never stored. Logs go to Workers Analytics Engine (the
// `LOG` binding) if it is configured; without it nothing is recorded.

import { checkTexts, checkNumbers } from "./check.js";

export const VERSION = "0.1.0";
export const MAX_PROSE_CHARS = 3000;
const MAX_BODY_BYTES = 1_000_000;
const PROTOCOL_VERSION = "2025-06-18";
const VOTE_LINE =
  "Would a hosted version or a review service be useful to you? Vote: https://github.com/cite-gate/cite-gate/discussions/1";
const BOT_UA = /bot|crawler|spider|curl|wget|python-requests|httpclient|uptime|monitor|healthcheck/i;

export const PRIVACY =
  "The hosted endpoint does not store your text. For each call it records the time, the tool name, " +
  "the pass/fail counts and the name your client reports, plus a daily-rotating hash of your IP so we " +
  "can count distinct users per day. Logs are kept for up to three months, then deleted automatically. For zero logging, run the local " +
  "server instead (python -m cite_gate.mcp_server).";

const TOOLS = [
  {
    name: "check_citations",
    description:
      "Check that every factual item in a script is backed by a quote that appears word for word in a source " +
      "text, that numbers and names in the prose appear in the quotes, and that the prose retells rather than " +
      `copies. Hosted limit: ${MAX_PROSE_CHARS} characters of prose per call; for longer scripts run the local server.`,
    inputSchema: {
      type: "object",
      properties: {
        claims: { type: "object", description: '{"config": {...}, "sections": [{"title": str, "items": [{"id": str, "text": str, "claims": [{"src": str, "quote": str}]}]}]}' },
        sources: { type: "object", description: "Map of source id -> full source text.", additionalProperties: { type: "string" } },
      },
      required: ["claims", "sources"],
    },
  },
  {
    name: "check_numbers",
    description: "List the numbers in a piece of prose that do not appear in any of the given quotes.",
    inputSchema: {
      type: "object",
      properties: { text: { type: "string" }, quotes: { type: "array", items: { type: "string" } } },
      required: ["text", "quotes"],
    },
  },
];

class ToolInputError extends Error {}

function proseChars(claims) {
  let n = 0;
  for (const s of claims.sections || []) for (const it of s.items || []) n += String(it.text || "").length;
  return n;
}

export function callTool(name, args) {
  if (name === "check_citations") {
    const { claims, sources } = args || {};
    if (!claims || typeof claims !== "object" || !sources || typeof sources !== "object") {
      throw new ToolInputError("'claims' and 'sources' must be objects");
    }
    const n = proseChars(claims);
    if (n > MAX_PROSE_CHARS) {
      throw new ToolInputError(
        `This hosted endpoint checks up to ${MAX_PROSE_CHARS} characters of prose per call (got ${n}). ` +
          "Split the script into smaller calls, or run the local server: pip install cite-gate, then python -m cite_gate.mcp_server.");
    }
    const rep = checkTexts(claims, sources);
    const result = { ...rep, passed: rep.failures.length === 0, note: VOTE_LINE, privacy: PRIVACY };
    return { body: { content: [{ type: "text", text: JSON.stringify(result, null, 1) }], isError: false },
             stats: { failures: rep.failures.length, warnings: rep.warnings.length } };
  }
  if (name === "check_numbers") {
    const { text, quotes } = args || {};
    if (typeof text !== "string" || !Array.isArray(quotes)) throw new ToolInputError("'text' must be a string and 'quotes' a list of strings");
    if (text.length > MAX_PROSE_CHARS) throw new ToolInputError(`text is limited to ${MAX_PROSE_CHARS} characters on the hosted endpoint`);
    const missing = checkNumbers(text, quotes);
    return { body: { content: [{ type: "text", text: JSON.stringify({ missing_numbers: missing, passed: missing.length === 0 }) }], isError: false },
             stats: { failures: missing.length, warnings: 0 } };
  }
  return null;
}

export function handle(msg, ctx = {}) {
  if (!msg || typeof msg !== "object" || Array.isArray(msg)) {
    return { jsonrpc: "2.0", id: null, error: { code: -32600, message: "invalid request" } };
  }
  const { method, id } = msg;
  if (id === undefined || id === null) return null; // notification
  const params = msg.params || {};
  try {
    if (method === "initialize") {
      if (params.clientInfo && ctx.onClient) ctx.onClient(params.clientInfo);
      return { jsonrpc: "2.0", id, result: { protocolVersion: params.protocolVersion || PROTOCOL_VERSION,
        capabilities: { tools: {} }, serverInfo: { name: "cite-gate", version: VERSION }, instructions: PRIVACY } };
    }
    if (method === "ping") return { jsonrpc: "2.0", id, result: {} };
    if (method === "tools/list") return { jsonrpc: "2.0", id, result: { tools: TOOLS } };
    if (method === "tools/call") {
      let out;
      try {
        out = callTool(params.name, params.arguments);
      } catch (e) {
        if (e instanceof ToolInputError || e instanceof Error) {
          if (ctx.onCall) ctx.onCall(params.name, { failures: -1, warnings: 0 });
          return { jsonrpc: "2.0", id, result: { content: [{ type: "text", text: e.message }], isError: true } };
        }
        throw e;
      }
      if (out === null) return { jsonrpc: "2.0", id, error: { code: -32602, message: `unknown tool '${params.name}'` } };
      if (ctx.onCall) ctx.onCall(params.name, out.stats);
      return { jsonrpc: "2.0", id, result: out.body };
    }
    return { jsonrpc: "2.0", id, error: { code: -32601, message: `method not found: ${method}` } };
  } catch (e) {
    return { jsonrpc: "2.0", id, error: { code: -32603, message: String(e && e.message).slice(0, 200) } };
  }
}

async function dailyHash(ip, salt) {
  const day = new Date().toISOString().slice(0, 10);
  const data = new TextEncoder().encode(`${salt}|${day}|${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].slice(0, 6).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function json(body, status = 200, headers = {}) {
  return new Response(body === null ? null : JSON.stringify(body), {
    status, headers: { "content-type": "application/json", ...headers },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/" && request.method === "GET") {
      return new Response(`cite-gate MCP endpoint. POST JSON-RPC to /mcp.\n\n${PRIVACY}\n`, { headers: { "content-type": "text/plain; charset=utf-8" } });
    }
    if (url.pathname !== "/mcp") return new Response("not found", { status: 404 });
    if (request.method !== "POST") return new Response("method not allowed", { status: 405, headers: { allow: "POST" } });
    const len = Number(request.headers.get("content-length") || 0);
    if (len > MAX_BODY_BYTES) return json({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "request too large" } }, 413);

    let msg;
    try {
      const text = await request.text();
      if (text.length > MAX_BODY_BYTES) return json({ jsonrpc: "2.0", id: null, error: { code: -32600, message: "request too large" } }, 413);
      msg = JSON.parse(text);
    } catch {
      return json({ jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }, 400);
    }

    const ua = request.headers.get("user-agent") || "";
    const kind = request.headers.get("x-cite-gate-self") === "1" ? "self" : BOT_UA.test(ua) ? "bot" : "user";
    const ip = request.headers.get("cf-connecting-ip") || "";
    let client = request.headers.get("mcp-client") || "";
    const events = [];
    const out = handle(msg, {
      onClient: (info) => { client = `${info.name || ""} ${info.version || ""}`.trim().slice(0, 60); },
      onCall: (tool, stats) => events.push({ tool, stats }),
    });

    if (env && env.LOG && events.length) {
      const source = ip && env.SALT ? await dailyHash(ip, env.SALT) : "";
      for (const e of events) {
        // blobs: tool, client, kind, source-hash · doubles: failures, warnings
        env.LOG.writeDataPoint({ blobs: [e.tool, client, kind, source], doubles: [e.stats.failures, e.stats.warnings], indexes: [e.tool] });
      }
    }
    if (out === null) return new Response(null, { status: 202 });
    return json(out);
  },
};
