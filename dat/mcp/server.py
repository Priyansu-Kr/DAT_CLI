"""DAT MCP (Model Context Protocol) server.

Exposes the same DAT capabilities available through the `dat` CLI -
git-aware documentation generation, an interactive screenshot-attaching
Preview Panel, environment diagnostics, and configuration inspection - as
MCP tools over a stdio
JSON-RPC 2.0 transport, so any MCP-compatible AI client/agent (Claude
Desktop, Claude Code, Cursor, etc.) can drive DAT directly.

Implemented directly against the wire protocol (JSON-RPC 2.0 framed as
newline-delimited JSON over stdio) rather than the official MCP SDK, to
keep DAT's dependency footprint minimal - the project already avoids
optional/heavy dependencies elsewhere (see setup.sh/pyproject.toml).

Protocol notes:
  - stdout is the transport channel. Nothing may ever be written there
    except JSON-RPC messages - all logs/diagnostics go to stderr, and tool
    execution runs with stdout redirected to a buffer so a misbehaving
    dependency calling print() can't corrupt the stream.
  - Requests (have an "id") always get a response. Notifications (no "id")
    never get one, even on error, per the JSON-RPC 2.0 spec.
  - Tool execution failures are reported as a normal tools/call *result*
    with isError: true (so the calling model can see and react to the
    failure text) - top-level JSON-RPC `error` objects are reserved for
    protocol-level problems (bad JSON, unknown method, invalid params).
"""
import contextlib
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from dat.models.doc_request import ChangeSummary
from dat.utils.container import Container

logger = logging.getLogger("dat.mcp")

# MCP protocol versions this server understands, most-recent first. If the
# client requests one we support we echo it back; otherwise we fall back to
# our latest, per the MCP version-negotiation rule.
SUPPORTED_PROTOCOL_VERSIONS: Tuple[str, ...] = ("2025-06-18", "2025-03-26", "2024-11-05")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

SERVER_NAME = "dat-mcp-server"
SERVER_INSTRUCTIONS = (
    "DAT (Developer Automation Toolkit) turns the current git branch into "
    "reviewable PR/feature documentation.\n\n"
    "EVERY request to document work in this repository follows the same "
    "three steps - 'generate a document', 'create documentation with test "
    "cases', 'document this through DAT', 'make a doc for these changes', "
    "with or without any mention of screenshots:\n"
    "  1. Call 'get_git_summary' for the branch, ticket and diff context.\n"
    "  2. Author the content yourself: 'key_points' (the code changes that "
    "were made) and 'test_cases' (concrete cases that verify them), plus "
    "'impact_areas' and 'overview'. You have far more context on the change "
    "than a fresh AI pass over the raw diff, so never leave these blank for "
    "DAT to guess.\n"
    "  3. Call 'open_preview' with that summary. It opens DAT's Preview "
    "Panel so the user reviews the content, drags in screenshots, and "
    "exports the DOCX themselves.\n\n"
    "'open_preview' is how a documentation request ends. Do not finish by "
    "writing a file instead - screenshots being unmentioned is not a reason "
    "to skip the panel. 'generate_document' exists only for an explicitly "
    "headless file (no review, e.g. CI) and refuses to run without "
    "confirm_headless: true. Use 'run_doctor' if a call fails with a "
    "missing-dependency error."
)

# Content the calling model must author itself before DAT will build a
# document: the code changes made, and the test cases that verify them.
REQUIRED_SUMMARY_FIELDS: Tuple[str, ...] = ("key_points", "test_cases")
_SUMMARY_FIELD_LABELS: Dict[str, str] = {
    "key_points": "key_points (the code changes that were made)",
    "test_cases": "test_cases (concrete cases that verify those changes)",
}


def _resolve_server_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("developer-automation-toolkit")
        except PackageNotFoundError:
            return "0.1.0"
    except ImportError:  # pragma: no cover - importlib.metadata ships with Python 3.8+
        return "0.1.0"


SERVER_VERSION = _resolve_server_version()

_JSON_SCHEMA_TYPES: Dict[str, Any] = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": (int, float),
    "array": list,
    "object": dict,
}

# Shared by both 'generate_document' and 'open_preview' - this is the shape
# an MCP client (an LLM with far more context on the actual change than a
# fresh AI call over the raw diff could infer) should fill in itself,
# instead of letting DAT's own AI provider guess.
_SUMMARY_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": (
        "AI-authored content describing the change, written by the calling model itself from its own "
        "understanding of the code/conversation - takes priority over DAT's built-in AI summary. Any "
        "field left out falls back to DAT's own generation for that field only."
    ),
    "properties": {
        "overview": {"type": "string", "description": "One-paragraph summary of what changed and why."},
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Bullet points describing the specific changes made.",
        },
        "impact_areas": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Modules/components/screens affected by the change.",
        },
        "test_recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "High-level guidance on how to verify the change.",
        },
        "test_cases": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Concrete, precise test case descriptions to verify the change.",
        },
    },
}


class ToolInputError(Exception):
    """The call was well-formed, but the caller must supply/do something first.

    Reported to the client as a tool error carrying the guidance verbatim
    (no "tool crashed" wrapper), so the model can correct itself and retry -
    which is how the required workflow stays enforced rather than merely
    documented.
    """


def _require_authored_content(args: Dict[str, Any], tool_name: str) -> None:
    """Step 2 of the workflow, enforced: the model writes the content.

    Without this the model can hand DAT an empty summary and ship a document
    whose "Changes Done" and "Test Cases" were guessed from the raw diff.
    """
    summary = args.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    missing = [field for field in REQUIRED_SUMMARY_FIELDS if not summary.get(field)]
    if not missing:
        return

    raise ToolInputError(
        f"'{tool_name}' needs the document's content first. Missing: "
        + "; ".join(_SUMMARY_FIELD_LABELS[field] for field in missing)
        + ". Read the change (call 'get_git_summary', and use what you already know from this "
        "conversation), then call this tool again with a 'summary' object containing "
        "key_points and test_cases - plus impact_areas and overview where you can. "
        "Do not leave them empty for DAT to guess."
    )


def _build_change_summary(summary_args: Optional[Dict[str, Any]]) -> Optional[ChangeSummary]:
    """Builds a ChangeSummary from the MCP 'summary' argument, or None if the
    caller didn't supply one (or supplied an empty object) - callers should
    treat None as "let DAT generate this itself"."""
    if not summary_args or not isinstance(summary_args, dict):
        return None
    if not any(summary_args.get(k) for k in ("overview", "key_points", "impact_areas", "test_recommendations", "test_cases")):
        return None
    return ChangeSummary(
        overview=summary_args.get("overview") or "",
        key_points=list(summary_args.get("key_points") or []),
        impact_areas=list(summary_args.get("impact_areas") or []),
        test_recommendations=list(summary_args.get("test_recommendations") or []),
        test_cases=list(summary_args.get("test_cases") or []),
    )


# How long to watch a freshly-launched Preview Panel process for an
# immediate crash (missing Tk/customtkinter, no DISPLAY on a headless VM,
# etc.) before declaring the launch successful. Bounded and short - long
# enough to catch a startup crash, short enough that 'open_preview' still
# returns promptly rather than blocking on the GUI's full lifetime.
_PREVIEW_LAUNCH_GRACE_SECONDS = 1.5
_PREVIEW_LAUNCH_POLL_INTERVAL = 0.1


def _write_seed_file(payload: Dict[str, Any]) -> str:
    """Writes a one-shot JSON handoff file for a detached 'generate-doc -s'
    subprocess to read and delete. Uses the OS temp directory so this works
    unmodified on macOS, Linux, and inside a VM without assuming any
    project-local scratch folder exists."""
    fd, path = tempfile.mkstemp(prefix="dat-preview-seed-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


def _spawn_detached(cmd: List[str], cwd: str) -> "subprocess.Popen":
    """Launches `cmd` as an independent background process that outlives
    this tool call - the MCP server must return immediately rather than
    blocking on however long the user takes to review/export in the GUI.

    stdout/stderr are captured to a temp log file (not a pipe: an unread
    pipe can deadlock a long-running child once its buffer fills) purely so
    an immediate crash can be diagnosed by `_wait_for_early_exit` below.
    `_wait_for_early_exit` removes the log file once the crash-detection
    window closes; if the process is still healthy at that point the log is
    deliberately left in the OS temp directory rather than tracked for
    later cleanup - it's a small text file in a location the OS/user
    session already reclaims routinely (macOS periodic /tmp cleanup,
    systemd-tmpfiles on Linux), not worth a cleanup mechanism of its own.
    """
    log_fd, log_path = tempfile.mkstemp(prefix="dat-preview-launch-", suffix=".log")
    log_file = os.fdopen(log_fd, "w", encoding="utf-8", errors="replace")

    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        # No process-group/session concept on Windows - detach via creation
        # flags instead so this subprocess survives the MCP server's own
        # process tree (e.g. if the IDE restarts the MCP server).
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0x00000008
        )
    else:
        # macOS/Linux: start a new session so the child isn't in this
        # process's session/group and isn't killed if the MCP server (or
        # its controlling terminal) exits.
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        close_fds=True,
        **popen_kwargs,
    )
    # The child inherits its own duplicated handle to this file at spawn
    # time - closing our copy here doesn't affect its writes, on any
    # platform, and avoids leaking an open file descriptor in this
    # long-lived server process.
    log_file.close()
    process._dat_log_path = log_path  # type: ignore[attr-defined]
    return process


def _wait_for_early_exit(process: "subprocess.Popen") -> Tuple[bool, Optional[str]]:
    """Watches `process` for up to _PREVIEW_LAUNCH_GRACE_SECONDS. Returns
    (True, None) if it's still running (the common, successful case) or
    (False, <captured output>) if it already exited - almost always a
    startup crash (missing dependency, no display) worth surfacing to the
    calling model instead of silently reporting success."""
    log_path: Optional[str] = getattr(process, "_dat_log_path", None)
    deadline = time.monotonic() + _PREVIEW_LAUNCH_GRACE_SECONDS
    while time.monotonic() < deadline and process.poll() is None:
        time.sleep(_PREVIEW_LAUNCH_POLL_INTERVAL)

    if process.poll() is None:
        return True, None

    detail = f"exit code {process.returncode}"
    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read().strip()
            if tail:
                detail = f"{detail}: {tail[-2000:]}"
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError):
                os.remove(log_path)
    return False, detail


def configure_logging(level: str = "WARNING") -> None:
    """Configure stderr-only logging for the MCP server process.

    stdout is the JSON-RPC transport - nothing but protocol messages may
    ever be written there, so every diagnostic must go to stderr instead.
    """
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.WARNING),
        format="%(asctime)s [%(levelname)s] dat.mcp: %(message)s",
        stream=sys.stderr,
    )


class MCPProtocolError(Exception):
    """A JSON-RPC/MCP protocol-level failure (bad method, bad params, etc.).

    Distinct from a tool raising during execution: that's reported inside
    a normal tools/call result with isError=true, not as one of these.
    """

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _validate_arguments(schema: Dict[str, Any], arguments: Dict[str, Any]) -> Optional[str]:
    """Best-effort validation of `arguments` against a tool's JSON inputSchema.

    Checks required-field presence, primitive type, and enum membership.
    Unknown extra fields are tolerated for forward compatibility. Returns a
    human-readable error string, or None if the arguments are acceptable.
    """
    properties: Dict[str, Any] = schema.get("properties", {})

    for required_field in schema.get("required", []):
        if arguments.get(required_field) is None:
            return f"missing required field '{required_field}'"

    for key, value in arguments.items():
        prop_schema = properties.get(key)
        if prop_schema is None or value is None:
            continue

        expected_type = prop_schema.get("type")
        py_type = _JSON_SCHEMA_TYPES.get(expected_type)
        if py_type is not None:
            # bool is a subclass of int in Python - don't let a stray
            # true/false silently pass an "integer"/"number" check.
            if expected_type in ("integer", "number") and isinstance(value, bool):
                return f"field '{key}' must be of type '{expected_type}', got boolean"
            if not isinstance(value, py_type):
                return f"field '{key}' must be of type '{expected_type}', got {type(value).__name__}"

        enum_values = prop_schema.get("enum")
        if enum_values is not None and value not in enum_values:
            return f"field '{key}' must be one of {enum_values!r}, got {value!r}"

    return None


class DATMCPServer:
    """MCP server exposing DAT services as tools over stdio JSON-RPC 2.0."""

    def __init__(self, container: Optional[Container] = None):
        self.container = container or Container.get_instance()
        self._initialized = False

        tool_specs: Tuple[Dict[str, Any], ...] = (
            {
                "name": "generate_document",
                "description": (
                    "HEADLESS ONLY - writes a DOCX/Markdown file straight to disk with no review. "
                    "This is NOT the tool for a normal 'generate a document' request: those must end "
                    "in 'open_preview' so the user can check the content, attach screenshots and "
                    "export themselves. Refuses to run unless confirm_headless is true, and requires "
                    "summary.key_points and summary.test_cases. Use it only when the user explicitly "
                    "asked for a file with no review (e.g. automation/CI), or as the fallback after "
                    "'open_preview' reported that no graphical session is available."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "output_path": {
                            "type": "string",
                            "description": "Destination file path. Defaults to '<title>.<format>' in the current directory.",
                        },
                        "title": {"type": "string", "description": "Override the inferred document title."},
                        "ticket": {"type": "string", "description": "Override the inferred ticket/issue ID (e.g. JIRA-1042)."},
                        "author": {"type": "string", "description": "Override the document author name."},
                        "approved_by": {"type": "string", "description": "Name of the approver for the 'Approved By' field."},
                        "images": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Local screenshot file paths to embed, in order.",
                        },
                        "summary": _SUMMARY_INPUT_SCHEMA,
                        "output_format": {
                            "type": "string",
                            "enum": ["docx", "md"],
                            "default": "docx",
                            "description": (
                                "Output document format. Leave as 'docx' unless the user explicitly "
                                "asked for Markdown."
                            ),
                        },
                        "confirm_headless": {
                            "type": "boolean",
                            "default": False,
                            "description": (
                                "Required acknowledgement that the user wants a file written with no "
                                "review in DAT's Preview Panel. Set true ONLY when they explicitly "
                                "asked for that, or when 'open_preview' already failed for lack of a "
                                "graphical session."
                            ),
                        },
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to the target git repository. Defaults to the server process's current working directory - set this when the client's cwd differs from the repo being documented.",
                        },
                    },
                },
                "handler_name": "_tool_generate_document",
            },
            {
                "name": "open_preview",
                "description": (
                    "THE way to fulfil any documentation request for this repo - 'generate a document', "
                    "'create documentation', 'generate test cases and put them in a document', 'document "
                    "this through DAT' - whether or not the user mentions screenshots. Opens DAT's "
                    "Preview Panel (a desktop GUI window) pre-filled with your summary, where the user "
                    "reviews the Changes Done / Test Cases content, drags in screenshots from anywhere on "
                    "disk, and exports the final DOCX themselves. Requires summary.key_points (the code "
                    "changes) and summary.test_cases (cases verifying them) - author them yourself before "
                    "calling. Returns as soon as the window launches: it does NOT wait for the user and "
                    "returns no final file path, so report that the panel is open rather than claiming a "
                    "file was produced. Needs a graphical session (local desktop, or forwarded X11/Wayland "
                    "on a remote VM); if none is available it fails fast, and only then fall back to "
                    "'generate_document' with confirm_headless: true."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Override the inferred document title."},
                        "ticket": {"type": "string", "description": "Override the inferred ticket/issue ID (e.g. JIRA-1042)."},
                        "author": {"type": "string", "description": "Override the document author name."},
                        "approved_by": {"type": "string", "description": "Name of the approver for the 'Approved By' field."},
                        "images": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Local screenshot file paths to pre-attach, in order. Optional - the user can also drag-and-drop more directly into the panel.",
                        },
                        "summary": _SUMMARY_INPUT_SCHEMA,
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to the target git repository. Defaults to the server process's current working directory.",
                        },
                    },
                },
                "handler_name": "_tool_open_preview",
            },
            {
                "name": "get_git_summary",
                "description": (
                    "Retrieves the current branch name, inferred title/ticket ID, "
                    "changed files, and recent commit history for a git repository. "
                    "Useful as context before calling generate_document."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_path": {
                            "type": "string",
                            "description": "Absolute path to the git repository. Defaults to the server process's current working directory.",
                        },
                        "max_changed_files": {
                            "type": "integer",
                            "default": 20,
                            "description": "Maximum number of changed file paths to include.",
                        },
                    },
                },
                "handler_name": "_tool_get_git_summary",
            },
            {
                "name": "run_doctor",
                "description": "Runs environment diagnostics on DAT's binary/package dependencies (git, python-docx, PyYAML).",
                "inputSchema": {"type": "object", "properties": {}},
                "handler_name": "_tool_run_doctor",
            },
            {
                "name": "get_config",
                "description": "Reads DAT's persisted configuration (author defaults, output directory, AI provider). Secrets are never returned, only whether they're set.",
                "inputSchema": {"type": "object", "properties": {}},
                "handler_name": "_tool_get_config",
            },
        )

        self._tools: Dict[str, Dict[str, Any]] = {
            spec["name"]: {**spec, "handler": getattr(self, spec["handler_name"])}
            for spec in tool_specs
        }

        self._method_handlers: Dict[str, Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = {
            "initialize": self._handle_initialize,
            "ping": self._handle_ping,
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "notifications/initialized": self._handle_initialized_notification,
            "notifications/cancelled": self._handle_cancelled_notification,
        }

    # --- MCP surface -------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": tool["name"], "description": tool["description"], "inputSchema": tool["inputSchema"]}
            for tool in self._tools.values()
        ]

    # --- JSON-RPC message handling ------------------------------------------

    def handle_request(self, request_json: str) -> Optional[str]:
        """Process one JSON-RPC message. Returns the response to write, or
        None if nothing should be written (the message was a notification).
        """
        try:
            message = json.loads(request_json)
        except json.JSONDecodeError as exc:
            return self._error_response(None, -32700, f"Parse error: {exc}")

        if not isinstance(message, dict):
            return self._error_response(None, -32600, "Invalid Request: expected a JSON object")

        if message.get("jsonrpc") != "2.0":
            return self._error_response(message.get("id"), -32600, "Invalid Request: 'jsonrpc' must be \"2.0\"")

        method = message.get("method")
        if not isinstance(method, str) or not method:
            return self._error_response(message.get("id"), -32600, "Invalid Request: 'method' must be a non-empty string")

        is_notification = "id" not in message
        req_id = message.get("id")

        params = message.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return None if is_notification else self._error_response(req_id, -32602, "Invalid params: 'params' must be an object")

        handler = self._method_handlers.get(method)
        if handler is None:
            return None if is_notification else self._error_response(req_id, -32601, f"Method not found: '{method}'")

        try:
            result = handler(params)
        except MCPProtocolError as exc:
            logger.debug("Protocol error handling '%s': %s", method, exc.message)
            return None if is_notification else self._error_response(req_id, exc.code, exc.message, exc.data)
        except Exception as exc:
            # Last-resort safety net. Tool-execution errors are already
            # caught and reported as isError results inside
            # _handle_tools_call, so reaching here means a genuine bug in
            # the server's protocol layer, not a tool failure.
            logger.exception("Unhandled exception handling method '%s'", method)
            return None if is_notification else self._error_response(req_id, -32603, f"Internal error: {exc}")

        if is_notification:
            return None
        return self._success_response(req_id, result or {})

    def _success_response(self, req_id: Any, result: Dict[str, Any]) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _error_response(self, req_id: Any, code: int, message: str, data: Any = None) -> str:
        error: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return json.dumps({"jsonrpc": "2.0", "id": req_id, "error": error})

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise MCPProtocolError(-32002, "Server not initialized: call 'initialize' before other requests")

    # --- Method handlers -----------------------------------------------------

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        requested_version = params.get("protocolVersion")
        negotiated_version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
        self._initialized = True
        return {
            "protocolVersion": negotiated_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": SERVER_INSTRUCTIONS,
        }

    def _handle_ping(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    def _handle_initialized_notification(self, params: Dict[str, Any]) -> None:
        logger.debug("Client acknowledged initialization")
        return None

    def _handle_cancelled_notification(self, params: Dict[str, Any]) -> None:
        logger.info("Client cancelled request id=%s reason=%s", params.get("requestId"), params.get("reason"))
        return None

    def _handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._require_initialized()
        return {"tools": self.list_tools()}

    def _handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self._require_initialized()

        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise MCPProtocolError(-32602, "Invalid params: 'name' is required and must be a string")

        tool = self._tools.get(tool_name)
        if tool is None:
            raise MCPProtocolError(-32602, f"Unknown tool: '{tool_name}'")

        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise MCPProtocolError(-32602, "Invalid params: 'arguments' must be an object")

        validation_error = _validate_arguments(tool["inputSchema"], arguments)
        if validation_error:
            raise MCPProtocolError(-32602, f"Invalid arguments for tool '{tool_name}': {validation_error}")

        return self._invoke_tool(tool_name, tool["handler"], arguments)

    def _invoke_tool(self, tool_name: str, handler: Callable[[Dict[str, Any]], Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
        # stdout is the JSON-RPC transport. Some underlying services print()
        # warnings (e.g. git/AI fallback notices) - redirect stdout to a
        # buffer for the duration of the call so a stray print can never
        # corrupt the wire protocol, and surface it as a log instead.
        stdout_buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout_buffer):
                data = handler(arguments)
        except ToolInputError as exc:
            # Actionable guidance, not a failure: pass it through verbatim so
            # the model reads an instruction rather than a stack-trace-ish
            # "tool crashed" message, and retries correctly.
            logger.info("Tool '%s' rejected the call: %s", tool_name, exc)
            return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:
            logger.exception("Tool '%s' raised during execution", tool_name)
            return {"content": [{"type": "text", "text": f"Error executing tool '{tool_name}': {exc}"}], "isError": True}
        finally:
            leaked = stdout_buffer.getvalue()
            if leaked:
                logger.warning("Tool '%s' wrote to stdout during execution (suppressed): %r", tool_name, leaked[:500])

        return {"content": [{"type": "text", "text": json.dumps(data, indent=2, default=str)}], "isError": False}

    # --- Tool implementations ------------------------------------------------

    def _tool_generate_document(self, args: Dict[str, Any]) -> Dict[str, Any]:
        # Writing a file straight to disk skips the review the user expects
        # from a documentation request, so it has to be asked for explicitly.
        if not args.get("confirm_headless"):
            raise ToolInputError(
                "A documentation request ends in DAT's Preview Panel, so the user can review the "
                "content, drag in screenshots and export the DOCX themselves: call 'open_preview' "
                "with your summary instead. Use 'generate_document' only when the user explicitly "
                "asked for a file written straight to disk with no review, or when 'open_preview' "
                "already failed because no graphical session is available - and then pass "
                "confirm_headless: true."
            )
        _require_authored_content(args, "generate_document")

        output_file = self.container.document_service.generate_documentation(
            output_path=args.get("output_path"),
            title_override=args.get("title"),
            author=args.get("author") or self.container.config.author_name,
            approved_by=args.get("approved_by") or "",
            ticket_override=args.get("ticket"),
            image_paths=args.get("images"),
            summary_override=_build_change_summary(args.get("summary")),
            output_format=args.get("output_format", "docx"),
            cwd=args.get("repo_path"),
        )
        return {"status": "success", "file_path": output_file}

    def _tool_open_preview(self, args: Dict[str, Any]) -> Dict[str, Any]:
        _require_authored_content(args, "open_preview")

        repo_path = args.get("repo_path") or os.getcwd()
        if not os.path.isdir(repo_path):
            raise RuntimeError(f"repo_path '{repo_path}' is not a directory")

        seed_path = _write_seed_file(
            {
                "title": args.get("title"),
                "ticket": args.get("ticket"),
                "author": args.get("author"),
                "approved_by": args.get("approved_by"),
                "images": list(args.get("images") or []),
                "summary": args.get("summary") or {},
            }
        )

        # Launched via the *current* interpreter (sys.executable) rather
        # than resolving 'dat' on PATH: this server's own install commonly
        # aliases 'dat' in an interactive shell rc file (see setup.sh),
        # which a non-interactive subprocess never sources. Re-invoking the
        # same interpreter that's already running this server guarantees
        # the exact same environment/install, on macOS, Linux, and inside a
        # VM alike.
        cmd = [sys.executable, "-m", "dat.main", "generate-doc", "-s", "--seed-file", seed_path]

        try:
            process = _spawn_detached(cmd, cwd=repo_path)
        except Exception as exc:
            with contextlib.suppress(OSError):
                os.remove(seed_path)
            raise RuntimeError(f"Failed to launch the Preview Panel process: {exc}") from exc

        ok, detail = _wait_for_early_exit(process)
        if not ok:
            raise RuntimeError(f"Preview Panel exited immediately (likely no graphical session available): {detail}")

        return {
            "status": "opened",
            "pid": process.pid,
            "message": (
                "The Preview Panel window has been launched and is running independently of this tool "
                "call, which already returned - it is NOT waiting for the user. Tell the user to review "
                "the pre-filled Changes Done / Test Cases content, drag-and-drop screenshot files onto "
                "the panel, and click Export when ready. This tool does not know the exported file's "
                "final path."
            ),
        }

    def _tool_get_git_summary(self, args: Dict[str, Any]) -> Dict[str, Any]:
        max_files = int(args.get("max_changed_files") or 20)
        git_info = self.container.git_service.get_git_info(cwd=args.get("repo_path"))
        return {
            "repo_name": git_info.repo_name,
            "branch_name": git_info.branch_name,
            "inferred_title": git_info.inferred_title,
            "ticket_id": git_info.ticket_id,
            "author_name": git_info.author_name,
            "changed_files_count": len(git_info.changed_files),
            "changed_files": git_info.changed_files[:max_files],
            "recent_commits": [
                {"hash": c.hash, "author": c.author, "date": c.date, "message": c.message}
                for c in git_info.recent_commits
            ],
        }

    def _tool_run_doctor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {
            "is_git_repo": self.container.git_adapter.is_git_repo(),
            "git_path": self.container.config.git_path,
            "ai_provider": self.container.config.ai_provider,
            "ai_configured": bool(self.container.config.ai_api_key),
            "config_file": self.container.configuration_service.config_file,
        }
        for module_name in ("docx", "yaml"):
            try:
                __import__(module_name)
                diagnostics[f"{module_name}_available"] = True
            except ImportError:
                diagnostics[f"{module_name}_available"] = False
        return diagnostics

    def _tool_get_config(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.container.config
        return {
            "author_name": cfg.author_name,
            "author_email": cfg.author_email,
            "default_output_dir": cfg.default_output_dir,
            "git_path": cfg.git_path,
            "ai_provider": cfg.ai_provider,
            "ai_api_key_configured": bool(cfg.ai_api_key),
            "config_file": self.container.configuration_service.config_file,
        }

    # --- Transport -------------------------------------------------------------

    def run_stdio_loop(self) -> None:
        for stream in (sys.stdin, sys.stdout):
            try:
                stream.reconfigure(encoding="utf-8", newline="\n")
            except (AttributeError, ValueError):
                pass  # not a reconfigurable TextIOWrapper (e.g. captured in tests) - defaults are fine

        logger.info("DAT MCP server listening on stdio (pid=%d)", os.getpid())
        try:
            for raw_line in sys.stdin:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    response = self.handle_request(line)
                except Exception:
                    logger.exception("Unrecoverable error handling a message; skipping it")
                    continue
                if response is not None:
                    sys.stdout.write(response + "\n")
                    sys.stdout.flush()
        except (BrokenPipeError, KeyboardInterrupt):
            pass
        finally:
            logger.info("DAT MCP server shutting down")


def main(argv: Optional[List[str]] = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="dat-mcp", description="DAT Model Context Protocol stdio server")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("DAT_MCP_LOG_LEVEL", "WARNING"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity written to stderr (stdout is reserved for JSON-RPC messages)",
    )
    parsed = parser.parse_args(argv)
    configure_logging(parsed.log_level)
    DATMCPServer().run_stdio_loop()


if __name__ == "__main__":
    main()
