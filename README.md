# Developer Automation Toolkit (DAT_CLI)

**DAT_CLI** is a cross-platform, IDE-independent toolkit designed to automate the tedious parts of developer documentation. It intelligently analyzes your Git repository to generate professional, formatted documentation in seconds.

---

## 🚀 Core Features

-   **Automatic Document Generation**: `dat generate-doc` builds the document and opens the Preview Panel to review and export it (`--headless` writes a `.docx`/`.md` straight to disk for automation).
-   **Smart Git Analysis**: Automatically parses your current branch name (e.g., `feature/PROJECT-123-topic`) to infer Ticket IDs and professional titles.
-   **AI-Powered Summaries**: Integrates with **Google Gemini** to read your `git diff` and write concise, professional "Changes Done" and "Test Case" summaries.
-   **Interactive Screenshot Selection**: Drag-and-drop screenshots onto the Preview Panel, or browse for them — you decide per document whether any are needed.
-   **Smart Image Layout**: 
    *   **Mobile Screenshots**: Automatically groups tall images side-by-side (2 per row).
    *   **Web Screenshots**: Places wide images at full page width for maximum clarity.
-   **Professional Templates**: Generates documents with a clean Arial-based layout, including Metadata Tables, Task Details, and Test Case sections.
-   **Custom Document Templates**: Build your own document structure visually in the GUI — see [Custom Document Templates](#-custom-document-templates).
-   **MCP Server**: Use `dat mcp` to expose DAT as tools to any MCP-compatible AI client (Claude Desktop, Claude Code, Cursor, etc.) — see [MCP Integration.md](MCP%20Integration.md).

---

## 🛠 Installation & Setup

### Prerequisites
*   **Python 3.9+**
*   **Git**

### Automated Setup (Recommended)
This toolkit includes a universal setup script that works on **Linux (Ubuntu/Debian)** and **macOS**.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Priyansu-Kr/DAT_CLI.git
    cd DAT_CLI
    ```

2.  **Run the setup script:**
    ```bash
    chmod +x setup.sh
    ./setup.sh
    ```

3.  **Refresh your terminal:**
    -   **Linux:** `source ~/.bashrc`
    -   **macOS:** `source ~/.zshrc`

---

## 🔑 AI Configuration (Optional but Recommended)

To enable the professional AI-powered summaries, get a free API key from [Google AI Studio](https://aistudio.google.com/app/apikey) and add it to your system:

```bash
# For Linux
echo 'export DAT_AI_KEY="YOUR_KEY_HERE"' >> ~/.bashrc && source ~/.bashrc

# For macOS
echo 'export DAT_AI_KEY="YOUR_KEY_HERE"' >> ~/.zshrc && source ~/.zshrc
```
*Note: If you don't set this, the tool will prompt you for it on the first run.*

---

## 📖 Usage

You can run `dat` from **any project folder** (Android, iOS, Web, etc.) once the setup is complete.

### Generate Feature Documentation
```bash
# Build the document and open the Preview Panel to review it,
# attach screenshots by drag-and-drop, and export (the default)
dat generate-doc

# Pre-attach specific local images, then review in the panel
dat generate-doc -i path/to/image1.png path/to/image2.png

# Automation/CI only: write the file straight to disk with no review
dat generate-doc --headless -o docs/feature.docx
```

The Preview Panel is the default destination so nothing is exported before you
have seen it and decided whether screenshots are needed. `--headless` is the
explicit opt-out; if no graphical session is available the command says so and
points at that flag rather than quietly writing a file.

### Other Commands
```bash
# Check if your environment is set up correctly
dat doctor

# View current configuration
dat config

# Start the MCP server (for AI client/IDE integration - see MCP Integration.md)
dat mcp
```

---

## 🧩 Custom Document Templates

Not every document fits the built-in layout. In the GUI (`dat gui`), the left
panel has a **Custom Document** section:

1.  **＋ Create Your Custom Doc** opens the Template Builder.
2.  Build the document from the **Components** palette — Heading, Subheading,
    Paragraph, Bullet List, Table, Image, Screenshots, Code Block, Two
    Columns, Separator.
3.  Group blocks into **Sections**. Each section can be reordered, hidden, and
    can optionally print its title as a document heading.
4.  **Layers** shows the document outline; **Preview** renders exactly what the
    exported `.docx` will contain.
5.  **Save Template** persists the structure and makes it the active document.

Once a template is active:

-   **Document Structure** in the left panel lists one show/hide switch per
    template section — the same hide/show behaviour as the built-in layout.
-   **Document Content** below it holds that structure's own components, ready
    to fill in. Edits show up in the preview as you type and are saved
    automatically — the preview rewrites the text of the widgets already on
    screen rather than redrawing the page, so it never flickers or jumps.
-   **Export DOCX** renders through the template.
-   The template (and which one was active) is remembered, so reopening DAT
    shows the same structure you built last time.

Templates are stored as one JSON file per template in `~/.dat/templates/`.

### Structure vs. content

The split is deliberate, and it decides where each control lives:

| | Set in | Example |
| --- | --- | --- |
| **Structure** | Template Builder | sections, block order, a table's **column** count, headings and widths |
| **Content** | Control Center → Document Content | the text itself, list items, and a table's **rows** — add as many as you need with **+ Add Row**, or remove one with **✕** |

So a table's columns are fixed when you design the document, while its rows
grow as you fill it in — exactly like **+ Add Test Case** on the standard
document.

### Column widths

Columns don't have to share the width evenly. Under each column heading in the
builder is a **− % +** control that sets that column's *relative* width, so an
Index / Case / Status table can be weighted 1 / 4 / 1:

```
Columns  − 3 +     ☑ Header row
[Index]  [Case                        ]  [Status]
− 17% +  −        67%                +   − 17% +
```

Widths are relative rather than fixed measurements, so the table stays correct
in the preview, at any page size, and in the exported `.docx` (which is written
with a fixed layout so Word keeps them instead of re-fitting to the text).

### Dynamic tokens

Any text field in a template can reference live values, resolved at render time:

| Token | Value |
| --- | --- |
| `{{title}}` | Ticket ID + topic |
| `{{ticket_id}}` (or `{{ticket}}`) | Ticket ID |
| `{{topic}}` | Feature topic |
| `{{author}}` / `{{approved_by}}` | Created By / Approved By |
| `{{branch}}` | Current git branch |
| `{{date}}` | Document date |
| `{{key_points}}` | AI key points, comma separated |
| `{{impact_areas}}` (or `{{modules}}`) | Affected modules |

Unknown tokens are left visible in the output so typos are easy to spot.

The Control Center only offers the shared fields your document actually uses:
**Created By** and **Approved By** belong to the built-in metadata table, so a
custom structure hides them — unless it writes `{{author}}` or
`{{approved_by}}`, in which case the field reappears so there is somewhere to
type the value.

---

## 🔍 What the AI actually sees

When DAT writes the summary itself (the `dat generate-doc` / GUI path), this is
the evidence it works from:

| | Source | Notes |
| --- | --- | --- |
| **Diff** | `git diff HEAD` + the content of new untracked files | Falls back to `<merge-base>..HEAD` — every commit on the branch — when the tree is clean, and to `HEAD~1..HEAD` only if there's no branch point |
| **File list** | `git status --porcelain -uall` | Individual files, renames reported by destination |
| **Commits** | `<merge-base>..HEAD` (up to 25) | This branch's own commits, not unrelated ones from `main` |

The diff is packed to a character budget that is **shared across files**, so a
20-file change is summarised from all 20 files rather than from whichever one
git printed first. Whatever doesn't fit is named in the prompt, so the model
can reference an omitted file without inventing its contents.

Raise or lower the budget with an environment variable (default 60,000
characters, roughly 15k tokens):

```bash
export DAT_AI_DIFF_CHAR_BUDGET=120000
```

New files matter here: `git diff` never shows untracked content, so without
DAT reading them a brand-new screen or class would be listed by name with its
code unseen. Binary and very large files are skipped, and your git index is
never modified.

None of this applies to the **MCP flow** — there the calling model authors
`key_points` and `test_cases` from its own reading of the code, and DAT's AI
provider isn't called at all.

---

## 📝 Document Structure
The generated document follows a standard professional template:
1.  **Heading**: [Ticket ID] - [Topic] 
2.  **Task Detail Table**: Includes Ticket No, Description, Date, and Author (Extracted from branch).
3.  **Changes Done**: High-level affected modules and brief AI-generated bullet points.
4.  **Test Cases Table**: A 3-column grid (Index, Case, Status) verifying the fix.
5.  **Screenshots**: Smartly positioned images with Test Case sub-headings.
