# DAT MCP Server

DAT ships a built-in [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server. It exposes the same
capabilities as the `dat` CLI — git-aware documentation generation, an interactive screenshot-attaching Preview
Panel, environment diagnostics, and configuration inspection — as **tools** any MCP-compatible AI client or IDE
agent (Claude Desktop, Claude Code, Cursor, VS Code Copilot, etc.) can call directly, in any project, without
you having to run `dat generate-doc` by hand.

Once connected, you can just ask your assistant things like *"generate the PR documentation for this branch"*
or *"check if my environment has everything DAT needs"*, and it will call the right tool for you.

---

## 1. Prerequisites

- DAT is installed and the `dat` command is on your `PATH` (run `./setup.sh` from the project root, or
  `pip install -e .` inside your virtualenv — see the main [README](README.md)).
- Verify it works: `dat doctor` should run without a "command not found" error.

No extra dependencies are required for the MCP server itself — it's part of the core `dat` package and talks
raw JSON-RPC 2.0 over stdio, so nothing beyond the base install is needed. `python-docx`/`customtkinter` are
only required by the individual *tools* that use them (`generate_document`, `open_preview`); the server itself
will start regardless, and each tool reports a clear error if its own dependency is missing.

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
| `generate_document` | Generates a DOCX or Markdown PR/feature doc from the current git branch's diff, commits, and screenshots — headless, no GUI |
| `open_preview` | Opens the interactive Preview Panel (GUI), pre-filled with your content, so a human can confirm it, drag-and-drop screenshots onto it, and export themselves |
| `get_git_summary` | Returns branch name, inferred title/ticket ID, changed files, and recent commits |
| `run_doctor` | Reports whether git/python-docx/PyYAML are available and configured |
| `get_config` | Reads DAT's persisted configuration (author defaults, output dir, AI provider) — secrets are never returned, only whether they're set |

### Bring your own summary: the `summary` argument

Both `generate_document` and `open_preview` accept an optional `summary` object. **You (the calling model) almost always have far more context on the actual change than DAT's own AI call over the raw diff could infer** — you've been in the conversation, you know which module changed and why. Fill this in yourself instead of leaving it to DAT:

| Field | Type | Description |
|---|---|---|
| `overview` | string | One-paragraph summary of what changed and why |
| `key_points` | string[] | Bullet points describing the specific changes made |
| `impact_areas` | string[] | Modules/components/screens affected |
| `test_recommendations` | string[] | High-level guidance on how to verify the change |
| `test_cases` | string[] | Concrete, precise test case descriptions to verify the change |

Any field you omit falls back to DAT's own AI generation for that field only. Omit `summary` entirely to let DAT generate everything itself, as before.

### `generate_document`

Headless: writes the file directly and returns its path. No human sees the content before it's final — use this when you're confident in the content and no screenshot needs attaching interactively.

| Argument | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | `<title>.<format>` | Destination file path |
| `title` | string | inferred from branch | Override the document title |
| `ticket` | string | inferred from branch | Override the ticket/issue ID |
| `author` | string | configured author | Override the author name |
| `approved_by` | string | *(empty)* | Name for the "Approved By" field |
| `images` | string[] | *(none)* | Local screenshot paths to embed, in order |
| `summary` | object | *(none)* | AI-authored content — see above. Omitted fields fall back to DAT's own AI generation |
| `output_format` | `"docx"` \| `"md"` | `"docx"` | Output format |
| `repo_path` | string | server's cwd | Absolute path to the target git repository |

Example prompt: *"Generate a Markdown PR doc for the current branch and save it as `PR.md`."*

### `open_preview`

Opens DAT's desktop Preview Panel pre-filled with the supplied `title`/`ticket`/`author`/`summary`, so a human can visually confirm the content, drag-and-drop screenshot files onto it from anywhere on disk (no folder or naming convention required), and click Export themselves. This is the recommended flow whenever a human should see and confirm AI-authored content — or attach a screenshot — before the document is final.

| Argument | Type | Default | Description |
|---|---|---|---|
| `title` | string | inferred from branch | Override the document title |
| `ticket` | string | inferred from branch | Override the ticket/issue ID |
| `author` | string | configured author | Override the author name |
| `approved_by` | string | *(empty)* | Name for the "Approved By" field |
| `images` | string[] | *(none)* | Local screenshot paths to pre-attach, in order — the user can still add more by drag-and-drop |
| `summary` | object | *(none)* | AI-authored content — see above |
| `repo_path` | string | server's cwd | Absolute path to the target git repository |

**This call does not block.** It launches the Preview Panel as an independent, detached process and returns as soon as the window is up — it does not wait for the user to review, attach screenshots, or export, and its result does not include a final file path (only `{"status": "opened", "pid": <int>}`). The window keeps running after the tool call returns; the user finishes the job by clicking **Export** inside it.

Requires a graphical session: a local desktop on macOS/Linux, or an X11/Wayland-forwarded display if the MCP server is running inside a VM/remote session. If none is available, the call fails immediately with a clear error (rather than hanging) — DAT watches the launched process for ~1.5s and surfaces its captured output if it exits in that window.

Example prompt: *"I just added biometric login to the auth flow. Write 3 precise test cases and the affected modules, then open the Preview Panel so I can attach a screenshot and export."*

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
  common causes are a missing `git` binary or a missing `python-docx`/`customtkinter` package.
- **Nothing seems to happen** — the server is silent by design (stdout is reserved for JSON-RPC only). Run
  `dat mcp --log-level DEBUG` and watch stderr, or check your MCP client's own connection logs.
- **Want to see exactly what's being called** — every tool invocation, its result, and any suppressed
  internal warnings are logged to stderr at `INFO`/`WARNING` level; nothing is ever written to stdout except
  protocol messages.
- **`open_preview` fails with "exited immediately"** — almost always means no graphical session is reachable
  from wherever `dat mcp` is running: a headless Linux VM/container with no `$DISPLAY`, or a missing
  `tkinter`/`customtkinter` install. Run `run_doctor` from the same environment, or `ssh -X`/VNC into the VM
  so a display is actually available, then retry.
- **`open_preview` returned "opened" but I don't see a window** — on some window managers a newly launched
  window can open behind existing ones or on another virtual desktop/Space; check your taskbar/Mission
  Control. The tool call itself only confirms the *process* survived its first ~1.5s, not that the window is
  focused.

---

## 7. Design & security notes

- **Transport**: newline-delimited JSON-RPC 2.0 over stdio, implementing the MCP `initialize` handshake,
  `ping`, `tools/list`, and `tools/call` methods, plus the `notifications/initialized` and
  `notifications/cancelled` notifications. Supports MCP protocol versions `2024-11-05`, `2025-03-26`, and
  `2025-06-18`.
- **stdout purity**: stdout carries only JSON-RPC messages. Every tool call runs with stdout redirected to an
  internal buffer, so even if an underlying service prints a warning, it's logged to stderr instead of
  corrupting the protocol stream.
- **Error semantics**: a tool that fails during execution (e.g. a missing `git` binary) is reported as a
  normal result with `isError: true` and a human-readable message, so your assistant can see what went wrong
  and react — it isn't treated as a protocol-level failure. Bad input (unknown tool, wrong argument type,
  invalid JSON) *is* a protocol-level error, per JSON-RPC/MCP conventions.
- **Secrets**: `get_config` reports whether an AI API key is configured, never the key's value. DAT never
  transmits secrets over the MCP channel.
- **Local trust model**: like any MCP stdio server, `dat mcp` runs as a local subprocess with your user's own
  permissions and file access — it doesn't add a network attack surface, but it can read/write anywhere you
  can.
- **`open_preview` is non-blocking by design**: the MCP server processes one JSON-RPC message at a time on a
  single stdio loop, so a tool call cannot sit and wait for a human to finish interacting with a GUI without
  freezing every other tool call (and likely tripping the client's own tool-call timeout). Instead,
  `open_preview` launches `python -m dat.main generate-doc -s --seed-file <path>` as a **detached** child
  process — `start_new_session=True` on macOS/Linux, `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` on Windows
  — that outlives the tool call, and returns immediately once a short (~1.5s) crash-detection window has
  passed. The child is launched via `sys.executable` (the same interpreter already running the MCP server),
  not by resolving `dat` on `PATH` — `setup.sh` wires `dat` up as a shell **alias**, which a non-interactive
  subprocess never inherits, so re-using the current interpreter is what makes this reliable across macOS,
  Linux, and a VM alike.
- **Seed file handoff**: the `title`/`ticket`/`author`/`summary`/`images` you pass to `open_preview` are
  written to a one-shot JSON file in the OS temp directory and handed to the `generate-doc` subprocess via
  `--seed-file`; that process deletes the file as soon as it's read (or immediately if it's malformed —
  the Preview Panel still opens with defaults rather than failing outright). Nothing is left behind on disk
  once the panel has loaded.
