"""Drive the real mnemosyne MCP server over stdio and require an answer to every tool call.

The server speaks JSON-RPC on its own stdin/stdout. Any child process it starts that inherits that
stdin (git, for the digest banner's sha) sits on the MCP channel, and on Windows the reply never
arrives. Importing the server can't see that; only a real round trip can, so this test spawns
`python -m mnemosyne.mcp_server`, initializes it, and calls tools that reach git.

It needs the optional `mcp` package. Without it the test skips, unless MNEMOSYNE_REQUIRE_MCP=1
(set in CI) turns the skip into a failure so a broken install can't hide the check.
"""
from __future__ import annotations

import importlib.util
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"

REPLY_TIMEOUT = 20  # seconds; a healthy server answers in well under one


class McpServerOverStdio(unittest.TestCase):
    def setUp(self):
        if importlib.util.find_spec("mcp") is None:
            if os.environ.get("MNEMOSYNE_REQUIRE_MCP") == "1":
                self.fail("MNEMOSYNE_REQUIRE_MCP=1 but the 'mcp' package is not installed")
            self.skipTest("the optional 'mcp' package is not installed")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.memory_repo = Path(self._tmp.name) / "memory-repo"
        (self.memory_repo / "memory").mkdir(parents=True)

        env = dict(os.environ, PYTHONPATH=str(MNEMOSYNE_SRC), MNEMOSYNE_REPO=str(self.memory_repo),
                   PYTHONUNBUFFERED="1")
        env.pop("MNEMOSYNE_CONFIG", None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "mnemosyne.mcp_server"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, cwd=self._tmp.name)
        self.addCleanup(self._stop)
        self.lines = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()
        self.next_id = 0

    def _pump(self):
        for raw in self.proc.stdout:
            self.lines.put(raw)

    def _stop(self):
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except OSError:
                pass
        self.proc.kill()
        self.proc.wait(timeout=10)

    def _send(self, message):
        self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _request(self, method, params):
        self.next_id += 1
        self._send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        while True:
            try:
                raw = self.lines.get(timeout=REPLY_TIMEOUT)
            except queue.Empty:
                self.fail(f"{method} {params.get('name', '')}: no reply within {REPLY_TIMEOUT}s")
            msg = json.loads(raw)
            if msg.get("id") == self.next_id:
                self.assertNotIn("error", msg, msg)
                return msg["result"]

    def _call(self, tool, **arguments):
        result = self._request("tools/call", {"name": tool, "arguments": arguments})
        self.assertFalse(result.get("isError"), result)
        return result

    def test_every_tool_call_gets_a_reply(self):
        self._request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                     "clientInfo": {"name": "mnemosyne-tests", "version": "0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools = {t["name"] for t in self._request("tools/list", {})["tools"]}
        self.assertTrue({"capture", "recall", "hygiene"} <= tools, tools)

        self._call("hygiene")
        saved = self._call("capture", title="Prefer feature flags for risky rollouts",
                           lesson="Wrap risky changes behind a feature flag and roll out gradually.",
                           tags="feature-flag,rollback")
        self.assertIn("saved", json.dumps(saved))
        digest = self._call("recall", query="a risky rollout", tags="feature-flag")
        self.assertIn("Prefer feature flags", json.dumps(digest))


if __name__ == "__main__":
    unittest.main()
