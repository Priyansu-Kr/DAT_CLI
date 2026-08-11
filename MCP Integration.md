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

- DAT is installed — either install path from the main [README](README.md) works.
- Verify it works: `dat doctor` should run without a "command not found" error.

### Find your `dat` launcher path

Every client config in §3 needs the **absolute path** to the `dat` launcher, never the bare word `dat`
(§3 explains why). Which path depends on how you installed DAT — find your case below.

#### Case A — you installed with pip

```bash
pip install --user developer-automation-toolkit
```

**Your launcher is `~/.local/bin/dat`** — written by pip, a real executable. Get the exact path to paste:

```bash
command -v dat
# /home/you/.local/bin/dat        ← use this, expanded, in the JSON
```

Client configs must use the **expanded** path (`/home/you/.local/bin/dat`), because `~` is a shell feature and
no MCP client expands it inside JSON. Other pip variants:

| How you installed | Launcher path |
| --- | --- |
| `pip install --user` (Linux) | `/home/<you>/.local/bin/dat` |
| `pip install --user` (macOS) | `/Users/<you>/Library/Python/3.x/bin/dat` |
| `pipx install` | `/home/<you>/.local/bin/dat` |
| Windows (`pip install --user`) | `C:\Users\<you>\AppData\Roaming\Python\Python3xx\Scripts\dat.exe` |

#### Case B — you cloned the repo and ran `setup.sh`

```bash
git clone https://github.com/Priyansu-Kr/DAT_CLI.git && cd DAT_CLI && ./setup.sh
```

`setup.sh` creates a virtualenv named `venv` in the repo root and installs DAT into it, so
**your launcher is `<repo>/venv/bin/dat`** — for a clone at `/home/you/DAT_CLI`, that is:

```
/home/you/DAT_CLI/venv/bin/dat
```

Print it exactly, from the repo root (`venv\Scripts\dat.exe` on Windows):

```bash
echo "$(pwd)/venv/bin/dat"
```

**`command -v dat` is not usable in this case.** `setup.sh` makes `dat` a shell **alias** in your `~/.bashrc`
(`~/.zshrc` on macOS), so `command -v dat` prints `alias dat='...'` rather than a path — and an alias exists
only inside your interactive shell, so **no MCP client can ever use it**. Take the path out of the alias, or
use the `echo` command above. If you made the venv yourself instead of running `setup.sh`, substitute its
name (e.g. `<repo>/.venv/bin/dat`).

> **Both cases, one rule:** whatever your case, the value you put in `"command"` is an absolute path ending in
> `/dat` that you can run directly in a terminal and get the server's silent stdio wait. Test it before
> editing any client config — `/full/path/to/dat doctor` should print the environment report.

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
directory it should start in. Point `command` at your `dat` launcher, `args` at `["mcp"]`, and set `cwd` to the
project you want it to operate on by default — you can always override the target repo per-call with the
`repo_path` argument (see §5), which is the recommended approach if you work across multiple projects with one
client.

**What to put in `"command"`, by install method** — the two values from §1, side by side:

| You installed with | `"command"` value |
| --- | --- |
| **pip** (`pip install --user developer-automation-toolkit`) | `"/home/you/.local/bin/dat"` |
| **clone + `setup.sh`** | `"/home/you/DAT_CLI/venv/bin/dat"` |

`"args"` is `["mcp"]` in both cases. Replace `you` with your username, and `/home/you/DAT_CLI` with wherever
you cloned the repo.

> **Never use the bare string `dat`.** A client spawns the server directly rather than through your interactive
> shell, so it never sources `~/.bashrc` / `~/.zshrc`. That breaks the bare form in two different ways: after a
> **pip** install, desktop apps started from a dock, Finder, or a launcher inherit only the session's base
> `PATH`, which on most distros excludes `~/.local/bin` where the launcher lives; after **`setup.sh`**, `dat`
> is only a shell alias, which no subprocess ever inherits. Either way you get `spawn dat ENOENT` /
> "command not found" in the client's logs even though `dat mcp` works perfectly in your terminal. An absolute
> path removes `PATH` from the equation and is correct for every client, so there is no reason to risk the
> bare form. The one place it is genuinely safe is `claude mcp add` run from your own terminal.

### Claude Desktop

Edit your `claude_desktop_config.json` (Claude → Settings → Developer → Edit Config). Claude Desktop is
GUI-launched, so the absolute path matters most here.

Installed with **pip**:

```json
{
  "mcpServers": {
    "dat": {
      "command": "/home/you/.local/bin/dat",
      "args": ["mcp"],
      "cwd": "/absolute/path/to/your/project"
    }
  }
}
```

Installed by **cloning the repo + `setup.sh`** — only the `command` line differs:

```json
{
  "mcpServers": {
    "dat": {
      "command": "/home/you/DAT_CLI/venv/bin/dat",
      "args": ["mcp"],
      "cwd": "/absolute/path/to/your/project"
    }
  }
}
```

On Windows, escape the backslashes: `"command": "C:\\Users\\you\\AppData\\Roaming\\Python\\Python311\\Scripts\\dat.exe"`
(pip) or `"command": "C:\\Users\\you\\DAT_CLI\\venv\\Scripts\\dat.exe"` (from source).

Restart Claude Desktop after saving. DAT's tools will appear under the 🔨 tool icon in the chat composer.

### Claude Code

From inside the target project directory:

```bash
claude mcp add dat -- dat mcp
```

That bare `dat` is the one safe use of it — `claude` runs in the terminal whose `PATH` you set up. It still
fails after `setup.sh`, whose `dat` is an alias, so pass the venv path explicitly:

```bash
claude mcp add dat -- /home/you/DAT_CLI/venv/bin/dat mcp     # clone + setup.sh
claude mcp add dat -- /home/you/.local/bin/dat mcp           # pip, also fine
```

Or add it directly to your project's `.mcp.json`, using your path from the table above:

```json
{
  "mcpServers": {
    "dat": {
      "command": "/home/you/.local/bin/dat",
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
      "command": "/home/you/.local/bin/dat",
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
      "command": "/home/you/.local/bin/dat",
      "args": ["mcp"]
    }
  }
}
```

Both examples show the **pip** path; installed from source, swap in `/home/you/DAT_CLI/venv/bin/dat`. Cursor and
VS Code are usually started from a dock or launcher, which is exactly the case where a bare `dat` fails.

### Any other MCP client

If your client isn't listed above, it almost certainly supports the same shape: a stdio-launched command with
arguments. Use `args: ["mcp"]` and, as `command`, your absolute launcher path from §1 —
`/home/you/.local/bin/dat` for pip, `/home/you/DAT_CLI/venv/bin/dat` for a clone + `setup.sh`. If your client
can't set a per-server `cwd`, always pass `repo_path` explicitly in tool calls instead (see below).

---

## 4. The documentation workflow

**Every** request to document work in a repo — *"generate a document"*, *"generate test cases and put
them in a document"*, *"document this through DAT"*, with or without any mention of screenshots — runs
the same three steps:

1. **`get_git_summary`** — branch, ticket and diff context.
2. **Author the content** — `key_points` (the code changes) and `test_cases` (concrete cases verifying
   them), plus `impact_areas` / `overview`. The calling model does this, not DAT's AI.
3. **`open_preview`** — opens the Preview Panel with that content, where the user reviews it, drags in
   screenshots, and exports the DOCX themselves.

This is enforced by the server, not left to prompt wording:

- `open_preview` and `generate_document` **refuse to run** without `summary.key_points` and
  `summary.test_cases`, returning guidance that tells the caller what to author and retry with.
- `generate_document` additionally requires **`confirm_headless: true`**, so a plain "make me a
  document" request can never quietly produce a `.docx`/`.md` file instead of opening the panel.

Both refusals come back as normal tool errors, so an MCP client reads them and corrects itself.

## 5. Available tools

| Tool | What it does |
|---|---|
| `open_preview` | **The endpoint for any documentation request.** Opens the Preview Panel (GUI) pre-filled with your content, so the user confirms it, drags screenshots onto it, and exports themselves |
| `generate_document` | **Headless only.** Writes a DOCX/Markdown file straight to disk with no review — requires `confirm_headless: true` |
| `get_git_summary` | Returns branch name, inferred title/ticket ID, changed files, and recent commits |
| `run_doctor` | Reports whether git/python-docx/PyYAML are available and configured |
| `get_config` | Reads DAT's persisted configuration (author defaults, output dir, AI provider) — secrets are never returned, only whether they're set |

### Bring your own summary: the `summary` argument

Both `generate_document` and `open_preview` take a `summary` object. **You (the calling model) almost always have far more context on the actual change than DAT's own AI call over the raw diff could infer** — you've been in the conversation, you know which module changed and why. Fill this in yourself instead of leaving it to DAT:

| Field | Type | Description |
|---|---|---|
| `overview` | string | One-paragraph summary of what changed and why |
| `key_points` | string[] | Bullet points describing the specific changes made |
| `impact_areas` | string[] | Modules/components/screens affected |
| `test_recommendations` | string[] | High-level guidance on how to verify the change |
| `test_cases` | string[] | Concrete, precise test case descriptions to verify the change |

`key_points` and `test_cases` are **required** by both document tools — the call is rejected with
guidance if either is missing or empty. The remaining fields are optional and fall back to DAT's own
AI generation for that field only.

### `generate_document`

Headless: writes the file directly and returns its path. No human sees the content before it's final,
so this is **not** the tool for a normal documentation request — use it only when the user explicitly
asked for a file with no review (automation/CI), or as the fallback after `open_preview` reported that
no graphical session is available.

| Argument | Type | Default | Description |
|---|---|---|---|
| `output_path` | string | `<title>.<format>` | Destination file path |
| `title` | string | inferred from branch | Override the document title |
| `ticket` | string | inferred from branch | Override the ticket/issue ID |
| `author` | string | configured author | Override the author name |
| `approved_by` | string | *(empty)* | Name for the "Approved By" field |
| `images` | string[] | *(none)* | Local screenshot paths to embed, in order |
| `summary` | object | *(none)* | AI-authored content — see above. Omitted fields fall back to DAT's own AI generation |
| `output_format` | `"docx"` \| `"md"` | `"docx"` | Output format — leave as `docx` unless Markdown was explicitly asked for |
| `confirm_headless` | boolean | `false` | **Required.** Acknowledges that the user wants a file with no review |
| `repo_path` | string | server's cwd | Absolute path to the target git repository |

Example prompt: *"Write a Markdown PR doc straight to `PR.md` without opening the panel."*

### `open_preview`

Opens DAT's desktop Preview Panel pre-filled with the supplied `title`/`ticket`/`author`/`summary`, so a human can visually confirm the content, drag-and-drop screenshot files onto it from anywhere on disk (no folder or naming convention required), and click Export themselves. This is how every documentation request finishes — a screenshot going unmentioned is not a reason to
skip it.

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

## 6. Working across multiple projects

An MCP client typically launches one `dat mcp` process per configured server entry, started with whatever
`cwd` you gave it (or the client's own working directory if you didn't). If you jump between repositories,
you have two options:

1. **One server entry per project**, each with its own `cwd` (simplest, shown in §3).
2. **One shared server entry**, passing `repo_path` explicitly on every `generate_document` /
   `get_git_summary` call — ask your assistant to do this, e.g. *"using repo_path `/path/to/other-project`,
   summarize the git changes there."*

---

## 7. Troubleshooting

- **The server never starts / `spawn dat ENOENT` / "command not found" in the client's logs** — the client
  can't resolve `dat`, even though your terminal can. This is the most common setup failure, and the fix is
  always to replace `"command": "dat"` with your absolute launcher path, then restart the client:
  `/home/you/.local/bin/dat` if you installed with **pip**, `/home/you/DAT_CLI/venv/bin/dat` if you **cloned
  the repo and ran `setup.sh`** (see §1). Confirm the path is right by running `<that path> doctor` in a
  terminal first — if that prints the environment report, the client will be able to launch it too.
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

## 8. Design & security notes

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
  not by resolving `dat` on `PATH`. That holds for either install shape: from source, `setup.sh` wires `dat` up
  as a shell **alias** that a non-interactive subprocess never inherits; from pip, the launcher is a real
  executable but may sit in a `~/.local/bin` that the client's `PATH` omits. Re-using the current interpreter
  sidesteps both — whichever Python is running the server already has the `dat` package importable — which is
  what makes this reliable across macOS, Linux, and a VM alike.
- **Seed file handoff**: the `title`/`ticket`/`author`/`summary`/`images` you pass to `open_preview` are
  written to a one-shot JSON file in the OS temp directory and handed to the `generate-doc` subprocess via
  `--seed-file`; that process deletes the file as soon as it's read (or immediately if it's malformed —
  the Preview Panel still opens with defaults rather than failing outright). Nothing is left behind on disk
  once the panel has loaded.
