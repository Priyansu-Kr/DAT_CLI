"""The MCP documentation workflow: author the content, then open the panel.

Exercised through real JSON-RPC requests, so these cover what an MCP client
actually sees.
"""
import json
import unittest
from unittest import mock

from dat.mcp import server as mcp_server
from dat.mcp.server import DATMCPServer

FULL_SUMMARY = {
    "overview": "Added a retry to the token refresh path.",
    "key_points": ["Added exponential backoff to TokenRefresher"],
    "test_cases": ["Refresh retries three times before failing"],
    "impact_areas": ["Auth"],
}


class FakeDocumentService:
    def __init__(self):
        self.calls = []

    def generate_documentation(self, **kwargs):
        self.calls.append(kwargs)
        return "/tmp/generated.docx"


class FakeGitService:
    def get_git_info(self, cwd=None):
        raise AssertionError("not used in these tests")


class FakeContainer:
    def __init__(self):
        self.document_service = FakeDocumentService()
        self.git_service = FakeGitService()
        self.config = mock.Mock(author_name="Dev", default_output_dir="./docs")
        self.configuration_service = mock.Mock(config_file="/tmp/dat/config.yaml")


class MCPTestCase(unittest.TestCase):
    def setUp(self):
        self.container = FakeContainer()
        self.server = DATMCPServer(container=self.container)
        self._initialize()

    def _initialize(self):
        self._request("initialize", {"protocolVersion": mcp_server.LATEST_PROTOCOL_VERSION}, req_id=0)

    def _request(self, method, params=None, req_id=1):
        raw = self.server.handle_request(json.dumps({
            "jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {},
        }))
        return json.loads(raw) if raw else None

    def _call(self, tool, arguments=None):
        response = self._request("tools/call", {"name": tool, "arguments": arguments or {}})
        return response["result"]

    @staticmethod
    def _text(result):
        return "\n".join(part["text"] for part in result["content"])


class TestWorkflowEnforcement(MCPTestCase):
    def test_open_preview_without_content_is_rejected_with_guidance(self):
        result = self._call("open_preview", {})
        self.assertTrue(result["isError"])

        text = self._text(result)
        self.assertIn("key_points", text)
        self.assertIn("test_cases", text)
        self.assertIn("get_git_summary", text)
        # Guidance, not a crash report.
        self.assertNotIn("Error executing tool", text)
        self.assertNotIn("Traceback", text)

    def test_open_preview_names_only_what_is_missing(self):
        result = self._call("open_preview", {"summary": {"key_points": ["did a thing"]}})
        text = self._text(result)
        self.assertTrue(result["isError"])
        self.assertIn("test_cases", text)
        self.assertNotIn("key_points (the code changes", text)

    def test_empty_lists_do_not_count_as_authored(self):
        result = self._call("open_preview", {"summary": {"key_points": [], "test_cases": []}})
        self.assertTrue(result["isError"])

    def test_wrong_typed_summary_is_caught_by_schema_validation(self):
        for bogus in ("a string", 42, []):
            response = self._request(
                "tools/call", {"name": "open_preview", "arguments": {"summary": bogus}}
            )
            self.assertIn("error", response, bogus)
            self.assertEqual(response["error"]["code"], -32602, bogus)
            self.assertIn("must be of type 'object'", response["error"]["message"])

    def test_null_summary_falls_through_to_the_content_guidance(self):
        result = self._call("open_preview", {"summary": None})
        self.assertTrue(result["isError"])
        self.assertIn("key_points", self._text(result))

    def test_open_preview_with_content_launches_the_panel(self):
        with mock.patch.object(mcp_server, "_spawn_detached") as spawn, \
                mock.patch.object(mcp_server, "_wait_for_early_exit", return_value=(True, None)), \
                mock.patch.object(mcp_server, "_write_seed_file", return_value="/tmp/seed.json"):
            spawn.return_value = mock.Mock(pid=4242)
            result = self._call("open_preview", {"summary": FULL_SUMMARY})

        self.assertFalse(result["isError"])
        payload = json.loads(self._text(result))
        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["pid"], 4242)
        self.assertTrue(spawn.called)

    def test_seed_file_carries_the_authored_summary(self):
        with mock.patch.object(mcp_server, "_spawn_detached") as spawn, \
                mock.patch.object(mcp_server, "_wait_for_early_exit", return_value=(True, None)), \
                mock.patch.object(mcp_server, "_write_seed_file", return_value="/tmp/seed.json") as seed:
            spawn.return_value = mock.Mock(pid=1)
            self._call("open_preview", {"summary": FULL_SUMMARY, "ticket": "X-1"})

        payload = seed.call_args[0][0]
        self.assertEqual(payload["summary"], FULL_SUMMARY)
        self.assertEqual(payload["ticket"], "X-1")


class TestHeadlessGate(MCPTestCase):
    def test_generate_document_redirects_to_the_preview_panel(self):
        result = self._call("generate_document", {"summary": FULL_SUMMARY})

        self.assertTrue(result["isError"])
        text = self._text(result)
        self.assertIn("open_preview", text)
        self.assertIn("confirm_headless", text)
        self.assertEqual(self.container.document_service.calls, [], "no file may be written")

    def test_markdown_request_without_the_flag_writes_nothing(self):
        """The reported bug: a doc request quietly producing an .md file."""
        result = self._call("generate_document", {
            "summary": FULL_SUMMARY, "output_format": "md", "output_path": "/tmp/out.md",
        })
        self.assertTrue(result["isError"])
        self.assertEqual(self.container.document_service.calls, [])

    def test_confirm_headless_still_requires_authored_content(self):
        result = self._call("generate_document", {"confirm_headless": True})
        self.assertTrue(result["isError"])
        self.assertIn("key_points", self._text(result))
        self.assertEqual(self.container.document_service.calls, [])

    def test_explicit_headless_with_content_writes_the_file(self):
        result = self._call("generate_document", {
            "confirm_headless": True, "summary": FULL_SUMMARY, "output_format": "docx",
        })

        self.assertFalse(result["isError"])
        payload = json.loads(self._text(result))
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["file_path"], "/tmp/generated.docx")

        call = self.container.document_service.calls[0]
        self.assertEqual(call["summary_override"].test_cases, FULL_SUMMARY["test_cases"])
        self.assertEqual(call["summary_override"].key_points, FULL_SUMMARY["key_points"])


class TestDiscoverability(MCPTestCase):
    def test_instructions_state_the_mandatory_sequence(self):
        result = self._request("initialize", {"protocolVersion": mcp_server.LATEST_PROTOCOL_VERSION})
        instructions = result["result"]["instructions"]

        for expected in ("get_git_summary", "key_points", "test_cases", "open_preview"):
            self.assertIn(expected, instructions)
        self.assertIn("confirm_headless", instructions)

    def test_open_preview_is_described_as_the_default_path(self):
        tools = {t["name"]: t for t in self.server.list_tools()}
        preview = tools["open_preview"]["description"].lower()
        headless = tools["generate_document"]["description"].lower()

        self.assertIn("screenshot", preview)
        self.assertIn("headless only", headless)
        self.assertIn("open_preview", headless)

    def test_generate_document_advertises_the_gate(self):
        tools = {t["name"]: t for t in self.server.list_tools()}
        schema = tools["generate_document"]["inputSchema"]["properties"]
        self.assertIn("confirm_headless", schema)
        self.assertEqual(schema["confirm_headless"]["type"], "boolean")
        self.assertFalse(schema["confirm_headless"]["default"])

    def test_unaffected_tools_still_work_without_a_summary(self):
        result = self._call("get_config")
        self.assertFalse(result["isError"])


if __name__ == "__main__":
    unittest.main()
