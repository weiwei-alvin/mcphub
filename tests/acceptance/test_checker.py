"""Tests of the verifier, NOT tests of MCP Hub or iPhone acceptance."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from email.message import Message

import check


class Response(io.BytesIO):
    def __init__(self, body, kind="application/json", status=200, session=None):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = kind
        if session:
            self.headers["Mcp-Session-Id"] = session
        self.status = status


class WireDouble:
    """In-memory transport double; never used by check.py in product mode."""
    def __init__(self, *, sse=False, wrong_id=False, error=False):
        self.requests = []
        self.sse, self.wrong_id, self.error = sse, wrong_id, error

    def open(self, request, timeout):
        self.requests.append(request)
        payload = json.loads(request.data)
        if "id" not in payload:
            return Response(b"", status=202)
        method = payload["method"]
        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "unit-double", "version": "0"}} if method == "initialize" else {"tools": [{"name": "echo"}]} if method == "tools/list" else {"content": [{"type": "text", "text": "known-value"}]}
        message = {"jsonrpc": "2.0", "id": payload["id"] + int(self.wrong_id)}
        message.update({"error": {"code": -32602, "message": "denied"}} if self.error else {"result": result})
        raw = json.dumps(message).encode()
        if self.sse:
            raw = b': heartbeat\n\ndata: {"jsonrpc":"2.0","method":"notifications/test"}\n\n' + b"data: " + raw + b"\n\n"
        return Response(raw, "text/event-stream" if self.sse else "application/json", session="unit-session")


class CheckerTests(unittest.TestCase):
    def test_result_mismatch_is_rejected(self):
        expectation = [{"path": ["content", 0, "text"], "equals": "right"}]
        check.check_expected({"content": [{"text": "right"}]}, expectation)
        with self.assertRaises(AssertionError):
            check.check_expected({"content": [{"text": "wrong"}]}, expectation)

    def test_error_and_empty_expectations_cannot_pass(self):
        for result, expected in [({"isError": True}, [{"path": ["isError"], "equals": True}]), ({}, []), ({}, [{"path": ["missing"], "equals": None}])]:
            with self.assertRaises(AssertionError):
                check.check_expected(result, expected)

    def test_private_url_boundaries(self):
        check.private_url("http://127.0.0.1:1/mcp", loopback_only=True)
        check.private_url("http://100.64.1.2:1/mcp", remote_only=True)
        for url, options in [("https://example.com/mcp", {}), ("http://user:secret@127.0.0.1/mcp", {}), ("http://127.0.0.1/mcp?token=secret", {}), ("http://127.0.0.1/mcp", {"remote_only": True}), ("https://host.ts.net/mcp", {"loopback_only": True})]:
            with self.assertRaises(check.SetupError):
                check.private_url(url, **options)

    def test_json_and_sse_protocol_and_headers(self):
        for sse in [False, True]:
            client = check.MCP("http://127.0.0.1:1/mcp", ["2025-06-18"])
            client.opener = wire = WireDouble(sse=sse)
            client.initialize()
            self.assertEqual(client.tool_names(), {"echo"})
            value = client.exchange("tools/call", {"name": "echo", "arguments": {}})
            check.check_expected(value, [{"path": ["content", 0, "text"], "equals": "known-value"}])
            headers = {k.lower(): v for k, v in wire.requests[-1].header_items()}
            self.assertEqual(headers["mcp-session-id"], "unit-session")
            self.assertEqual(headers["mcp-protocol-version"], "2025-06-18")
            self.assertEqual(headers["accept"], "application/json, text/event-stream")

    def test_wrong_rpc_id_rejected(self):
        client = check.MCP("http://127.0.0.1:1/mcp", ["2025-06-18"])
        client.opener = WireDouble(wrong_id=True)
        with self.assertRaises(AssertionError):
            client.initialize()

    def test_rpc_error_not_success(self):
        client = check.MCP("http://127.0.0.1:1/mcp", ["2025-06-18"])
        client.opener = WireDouble(error=True)
        with self.assertRaises(check.RPCError):
            client.initialize()

    def test_sse_without_matching_response_rejected(self):
        with self.assertRaises(AssertionError):
            check.MCP._sse_response(io.BytesIO(b'data: {"id":99}\n\n'), 1)

    def test_unsupported_negotiated_protocol_rejected(self):
        client = check.MCP("http://127.0.0.1:1/mcp", ["not-supported-by-double"])
        client.opener = WireDouble()
        with self.assertRaises(AssertionError):
            client.initialize()

    def test_all_ticket_commands_fail_closed_without_fixture(self):
        env = dict(os.environ)
        env.pop("MCP_HUB_ACCEPTANCE_CONFIG", None)
        env.pop("MCP_HUB_ACCEPTANCE_ALLOW_MUTATION", None)
        program = Path(__file__).with_name("check.py")
        for n in range(1, 12):
            with self.subTest(ticket=n):
                result = subprocess.run([sys.executable, "-B", str(program), "--ticket", f"T-{n:03d}"], env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn("UNVERIFIED", result.stderr)
                self.assertNotIn("AUTOMATED_CHECK_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
