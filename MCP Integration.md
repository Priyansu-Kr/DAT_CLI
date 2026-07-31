# DAT MCP Server

DAT ships a built-in [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server. It exposes the same
capabilities as the `dat` CLI — git-aware documentation generation, ADB screenshot capture, environment
diagnostics, and configuration inspection — as **tools** any MCP-compatible AI client or IDE agent (Claude
Desktop, Claude Code, Cursor, VS Code Copilot, etc.) can call directly, in any project, without you having to
run `dat generate-doc` by hand.

Once connected, you can just ask your assistant things like *"generate the PR documentation for this branch"*
or *"check if my environment has everything DAT needs"*, and it will call the right tool for you.

---

## 1. Prerequisites

- DAT is installed and the `dat` command is on your `PATH` (run `./setup.sh` from the project root, or
  `pip install -e .` inside your virtualenv — see the main [README](README.md)).
- Verify it works: `dat doctor` should run without a "command not found" error.

No extra dependencies are required for the MCP server itself — it's part of the core `dat` package and talks
raw JSON-RPC 2.0 over stdio, so nothing beyond the base install is needed. `python-docx`/`customtkinter`/`adb`
are only required by the individual *tools* that use them (e.g. `generate_document`, `take_screenshot`); the
server itself will start regardless, and each tool reports a clear error if its own dependency is missing.

---

## 2. Starting the server manually (for testing/debugging)

You normally won't run this yourself — your MCP client launches it for you (see §3). To sanity-check the
server directly:

```bash
dat mcp
```

It will sit there silently, reading JSON-RPC requests from stdin and writing responses to stdout — that's
expected, it's designed to be driven by a client, not typed into by a human. Press `Ctrl+C` to stop it.

To see what it's doing, enable verbose logging (written to **stderr only**, never stdout, so it can't corrupt
the protocol stream):

```bash
dat mcp --log-level DEBUG
# or
DAT_MCP_LOG_LEVEL=DEBUG dat mcp
```

---

## 3. Connecting an MCP client

All MCP clients boil down to the same thing: a command to launch the server, plus (optionally) the working
directory it should start in. Point `command` at `dat`, `args` at `["mcp"]`, and set `cwd` to the project you
want it to operate on by default — you can always override the target repo per-call with the `repo_path`
argument (see §4), which is the recommended approach if you work across multiple projects with one client.

### Claude Desktop

Edit your `claude_desktop_config.json` (Claude → Settings → Developer → Edit Config):

```json
{
  "mcpServers": {
    "dat": {
      "command": "dat",
      "args": ["mcp"],
      "cwd": "/absolute/path/to/your/project"
    }
  }
}
```

Restart Claude Desktop after saving. DAT's tools will appear under the 🔨 tool icon in the chat composer.

### Claude Code

From inside the target project directory:

```bash
claude mcp add dat -- dat mcp
```

Or add it directly to your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "dat": {
      "command": "dat",
      "args": ["mcp"]
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` (project-level) or your global Cursor MCP settings:

```json
{
  "mcpServers": {
    "dat": {
      "command": "dat",
      "args": ["mcp"]
    }
  }
}
```

### VS Code (GitHub Copilot Chat / other MCP-aware extensions)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "dat": {
      "type": "stdio",
      "command": "dat",
      "args": ["mcp"]
    }
  }
}
```

### Any other MCP client

If your client isn't listed above, it almost certainly supports the same shape: a stdio-launched command with
arguments. Use `command: "dat"`, `args: ["mcp"]`. If your client can't set a per-server `cwd`, always pass
`repo_path` explicitly in tool calls instead (see below).

---

## 4. Available tools

| Tool | What it does |
|---|---|
| `generate_document` | Generates a DOCX or Markdown PR/feature doc from the current git branch's diff, commits, and screenshots |
| `take_screenshot` | Captures a screenshot from a connected Android device/emulator via ADB |
| `get_git_summary` | Returns branch name, inferred title/ticket ID, changed files, and recent commits |
| `run_doctor` | Reports whether git/adb/python-docx/PyYAML are available and configured |
| `get_config` | Reads DAT's persisted configuration (author defaults, output dir, AI provider) — secrets are never returned, only whether they're set |

### `generate_document`

| Argument | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | `<title>.<format>` | Destination file path |
| `title` | string | inferred from branch | Override the document title |
| `ticket` | string | inferred from branch | Override the ticket/issue ID |
| `author` | string | configured author | Override the author name |
| `approved_by` | string | *(empty)* | Name for the "Approved By" field |
| `images` | string[] | *(none)* | Local screenshot paths to embed, in order |
| `capture_adb` | boolean | `false` | Also capture a screenshot from a connected Android device |
| `output_format` | `"docx"` \| `"md"` | `"docx"` | Output format |
| `repo_path` | string | server's cwd | Absolute path to the target git repository |

Example prompt: *"Generate a Markdown PR doc for the current branch and save it as `PR.md`."*

### `take_screenshot`

| Argument | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | temp-dir file | Destination PNG path |
| `device_id` | string | first connected device | Specific ADB device serial |

### `get_git_summary`

| Argument | Type | Default | Description |
|---|---|---|---|
| `repo_path` | string | server's cwd | Absolute path to the git repository |
| `max_changed_files` | integer | `20` | Max number of changed file paths to include |

Example prompt: *"What's changed on my current branch?"*

### `run_doctor` / `get_config`

Take no arguments.

Example prompt: *"Does my environment have everything DAT needs to generate docs?"*

---

## 5. Working across multiple projects

An MCP client typically launches one `dat mcp` process per configured server entry, started with whatever
`cwd` you gave it (or the client's own working directory if you didn't). If you jump between repositories,
you have two options:

1. **One server entry per project**, each with its own `cwd` (simplest, shown in §3).
2. **One shared server entry**, passing `repo_path` explicitly on every `generate_document` /
   `get_git_summary` call — ask your assistant to do this, e.g. *"using repo_path `/path/to/other-project`,
   summarize the git changes there."*

---

## 6. Troubleshooting

- **"Server not initialized" error** — the client didn't send the MCP `initialize` handshake first. This
  indicates a client bug, not a DAT issue; the server rejects `tools/list`/`tools/call` before `initialize`
  by design (per the MCP spec).
- **A tool call fails immediately** — run `run_doctor` (or `dat doctor` from a terminal) first; the most
  common causes are a missing `git`/`adb` binary or a missing `python-docx`/`customtkinter` package.
- **ADB-related tools fail** — `take_screenshot` and `generate_document`'s `capture_adb` option need an
  Android device/emulator connected and visible to `adb devices`. This is optional; document generation
  works fine without it.
- **Nothing seems to happen** — the server is silent by design (stdout is reserved for JSON-RPC only). Run
  `dat mcp --log-level DEBUG` and watch stderr, or check your MCP client's own connection logs.
- **Want to see exactly what's being called** — every tool invocation, its result, and any suppressed
  internal warnings are logged to stderr at `INFO`/`WARNING` level; nothing is ever written to stdout except
  protocol messages.

---

## 7. Design & security notes

- **Transport**: newline-delimited JSON-RPC 2.0 over stdio, implementing the MCP `initialize` handshake,
  `ping`, `tools/list`, and `tools/call` methods, plus the `notifications/initialized` and
  `notifications/cancelled` notifications. Supports MCP protocol versions `2024-11-05`, `2025-03-26`, and
  `2025-06-18`.
- **stdout purity**: stdout carries only JSON-RPC messages. Every tool call runs with stdout redirected to an
  internal buffer, so even if an underlying service prints a warning, it's logged to stderr instead of
  corrupting the protocol stream.
- **Error semantics**: a tool that fails during execution (e.g. no ADB device connected) is reported as a
  normal result with `isError: true` and a human-readable message, so your assistant can see what went wrong
  and react — it isn't treated as a protocol-level failure. Bad input (unknown tool, wrong argument type,
  invalid JSON) *is* a protocol-level error, per JSON-RPC/MCP conventions.
- **Secrets**: `get_config` reports whether an AI API key is configured, never the key's value. DAT never
  transmits secrets over the MCP channel.
- **Local trust model**: like any MCP stdio server, `dat mcp` runs as a local subprocess with your user's own
  permissions and file access — it doesn't add a network attack surface, but it can read/write anywhere you
  can.
