# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 MLPC Inc.
"""Minimal Model Context Protocol server over stdio (JSON-RPC 2.0, one message per line).

No dependencies and no network access: it runs on the user's machine, reads nothing but the
arguments it is given, and sends nothing anywhere. There is no telemetry.

    python -m cite_gate.mcp_server

Tools:
  * check_citations — claims document + source texts -> failures and warnings
  * check_numbers   — one piece of prose + its quotes -> numbers that are not in the quotes
"""
from __future__ import annotations

import json
import sys

from . import __version__
from .check import check_texts, numbers

PROTOCOL_VERSION = "2025-06-18"
VOTE_LINE = ("Would a hosted version or a review service be useful to you? "
             "Vote: https://github.com/cite-gate/cite-gate/discussions")

TOOLS = [
    {
        "name": "check_citations",
        "description": (
            "Check that every factual item in a script is backed by a quote that appears word for word "
            "in a source text, that numbers and names in the prose appear in the quotes, and that the "
            "prose retells rather than copies. Returns failures (must fix) and warnings (review)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "object",
                    "description": ("{\"config\": {...optional...}, \"sections\": [{\"title\": str, \"items\": "
                                    "[{\"id\": str, \"text\": str, \"claims\": [{\"src\": str, \"quote\": str}]}]}]}"),
                },
                "sources": {
                    "type": "object",
                    "description": "Map of source id -> full source text.",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["claims", "sources"],
        },
    },
    {
        "name": "check_numbers",
        "description": "List the numbers in a piece of prose that do not appear in any of the given quotes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "quotes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text", "quotes"],
        },
    },
]


class UnknownTool(Exception):
    pass


def call_tool(name: str, args: dict) -> dict:
    if name == "check_citations":
        claims, sources = args.get("claims"), args.get("sources")
        if not isinstance(claims, dict) or not isinstance(sources, dict):
            raise ValueError("'claims' and 'sources' must be objects")
        rep = check_texts(claims, {str(k): str(v) for k, v in sources.items()})
        result = {**rep.as_dict(), "passed": not rep.failures, "note": VOTE_LINE}
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                "isError": False}
    if name == "check_numbers":
        text, quotes = args.get("text"), args.get("quotes")
        if not isinstance(text, str) or not isinstance(quotes, list):
            raise ValueError("'text' must be a string and 'quotes' a list of strings")
        missing = sorted(numbers(text) - numbers(" ".join(str(q) for q in quotes)))
        result = {"missing_numbers": missing, "passed": not missing}
        return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}
    raise UnknownTool(name)


def handle(msg) -> dict | None:
    """Return a JSON-RPC response, or None for notifications."""
    if not isinstance(msg, dict):        # batches and bare values are not supported
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:                      # notification (e.g. notifications/initialized)
        return None
    try:
        if method == "initialize":
            result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", PROTOCOL_VERSION),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "cite-gate", "version": __version__}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                result = call_tool(p.get("name", ""), p.get("arguments") or {})
            except UnknownTool:
                return {"jsonrpc": "2.0", "id": mid,
                        "error": {"code": -32602, "message": f"unknown tool {p.get('name')!r}"}}
            except ValueError as e:
                result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    except Exception as e:  # noqa: BLE001 — never crash the stdio loop on one bad request
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)[:200]}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
