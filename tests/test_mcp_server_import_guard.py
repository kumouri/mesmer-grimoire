"""Regression test for the MCP server import guard's error-attribution bug.

`mnemosyne.mcp_server` wraps `from mcp.server.fastmcp import FastMCP` in `except ImportError`
and used to always report "the MCP server needs the 'mcp'
package", even when 'mcp' was installed but the submodule import failed for another reason
(e.g. mcp 2.x renamed FastMCP to MCPServer). This test exercises `_mcp_import_error` directly —
no network install of `mcp` required — to make sure the guard distinguishes the two cases and
always surfaces the real underlying error text.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"

if str(MNEMOSYNE_SRC) not in sys.path:
    sys.path.insert(0, str(MNEMOSYNE_SRC))


class McpImportGuard(unittest.TestCase):
    def _load_guard(self):
        # `mnemosyne.mcp_server` raises SystemExit at import time when 'mcp' isn't
        # installed, so exercise the helper via a source-level exec rather than importing
        # the module — this keeps the test independent of whether 'mcp' happens to be
        # installed in the test environment.
        source = (MNEMOSYNE_SRC / "mnemosyne" / "mcp_server.py").read_text(encoding="utf-8")
        func_src = source.split("try:\n    from mcp.server.fastmcp import FastMCP")[0]
        namespace: dict = {}
        exec(compile(func_src, "mcp_server_guard", "exec"), namespace)
        return namespace["_mcp_import_error"]

    def test_reports_missing_package_when_mcp_is_absent(self):
        mcp_import_error = self._load_guard()
        # Deterministic regardless of whether 'mcp' happens to be installed in the
        # environment actually running this test.
        with patch.object(importlib.util, "find_spec", return_value=None):
            exc = ModuleNotFoundError("No module named 'mcp'")
            result = mcp_import_error(exc)
        self.assertIsInstance(result, SystemExit)
        self.assertIn("needs the 'mcp' package", str(result))

    def test_does_not_blame_missing_package_when_mcp_is_installed(self):
        mcp_import_error = self._load_guard()
        # Simulate 'mcp' being importable (as it is post mcp>=2, where the pin in this repo
        # now prevents this from happening in practice, but the guard must still tell the
        # truth if it ever does).
        fake_spec = importlib.util.spec_from_loader("mcp", loader=None)
        with patch.object(importlib.util, "find_spec", return_value=fake_spec):
            exc = ModuleNotFoundError(
                "No module named 'mcp.server.fastmcp'. This is mcp 2.x, where FastMCP was "
                "renamed to MCPServer"
            )
            result = mcp_import_error(exc)
        self.assertIsInstance(result, SystemExit)
        message = str(result)
        self.assertNotIn("needs the 'mcp' package", message)
        self.assertIn("found an installed 'mcp' package", message)
        self.assertIn("renamed to MCPServer", message)


if __name__ == "__main__":
    unittest.main()
