import json
import subprocess
import sys
import unittest
from pathlib import Path

from cite_gate.mcp_server import handle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "The harbour held 1,200 ships in 1850. A lighthouse stood on the eastern pier."


def call(name, args, mid=1):
    return handle({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                   "params": {"name": name, "arguments": args}})


class Protocol(unittest.TestCase):
    def test_initialize_and_list(self):
        r = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(r["result"]["serverInfo"]["name"], "cite-gate")
        self.assertIn("tools", r["result"]["capabilities"])
        r = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual({t["name"] for t in r["result"]["tools"]}, {"check_citations", "check_numbers"})

    def test_non_object_message_is_rejected_not_crashing(self):
        self.assertEqual(handle([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])["error"]["code"], -32600)
        self.assertEqual(handle(123)["error"]["code"], -32600)

    def test_notification_has_no_reply(self):
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method_and_tool(self):
        self.assertEqual(handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})["error"]["code"], -32601)
        self.assertEqual(call("nope", {})["error"]["code"], -32602)


class Tools(unittest.TestCase):
    def test_check_citations_pass_and_fail(self):
        claims = {"sections": [{"items": [
            {"id": "ok", "text": "The harbour had room for 1,200 ships by 1850.",
             "claims": [{"src": "town", "quote": "The harbour held 1,200 ships in 1850."}]},
            {"id": "bad", "text": "It held 1,500 ships.",
             "claims": [{"src": "town", "quote": "The harbour held 1,200 ships in 1850."}]}]}]}
        r = call("check_citations", {"claims": claims, "sources": {"town": SOURCE}})
        body = json.loads(r["result"]["content"][0]["text"])
        self.assertFalse(body["passed"])
        self.assertEqual([f["item"] for f in body["failures"]], ["bad"])
        self.assertIn("discussions", body["note"])

    def test_bad_arguments_are_tool_errors(self):
        r = call("check_citations", {"claims": "x", "sources": {}})
        self.assertTrue(r["result"]["isError"])

    def test_check_numbers(self):
        r = call("check_numbers", {"text": "In 1851 about 6,000,000 came.", "quotes": ["In 1851 six million came."]})
        body = json.loads(r["result"]["content"][0]["text"])
        self.assertEqual(body["missing_numbers"], ["6000000"])


class Stdio(unittest.TestCase):
    def test_round_trip_over_stdio(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        p = subprocess.run([sys.executable, "-m", "cite_gate.mcp_server"], cwd=ROOT,
                           input="\n".join(json.dumps(m) for m in msgs) + "\nnot json\n",
                           capture_output=True, text=True, timeout=30)
        lines = [json.loads(x) for x in p.stdout.splitlines() if x.strip()]
        self.assertEqual([x.get("id") for x in lines], [1, 2, None])
        self.assertEqual(lines[2]["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
