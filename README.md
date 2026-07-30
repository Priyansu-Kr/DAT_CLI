# Developer Automation Toolkit (DAT_CLI)

**DAT_CLI** is a cross-platform, IDE-independent toolkit designed to automate the tedious parts of developer documentation. It intelligently analyzes your Git repository to generate professional, formatted documentation in seconds.

---

## 🚀 Core Features

-   **Automatic Document Generation**: Use `dat generate-doc` to create `.docx` or `.md` files.
-   **Smart Git Analysis**: Automatically parses your current branch name (e.g., `feature/PROJECT-123-topic`) to infer Ticket IDs and professional titles.
-   **AI-Powered Summaries**: Integrates with **Google Gemini** to read your `git diff` and write concise, professional "Changes Done" and "Test Case" summaries.
-   **Interactive Screenshot Selection**: Use the `-s` flag to open a native file picker window to select multiple screenshots from your computer.
-   **Smart Image Layout**: 
    *   **Mobile Screenshots**: Automatically groups tall images side-by-side (2 per row).
    *   **Web Screenshots**: Places wide images at full page width for maximum clarity.
-   **Professional Templates**: Generates documents with a clean Arial-based layout, including Metadata Tables, Task Details, and Test Case sections.

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
# Generate doc and open window to select screenshots
dat generate-doc -s

# Generate doc for specific local images
dat generate-doc -i path/to/image1.png path/to/image2.png
```

### Other Commands
```bash
# Check if your environment is set up correctly
dat doctor

# View current configuration
dat config
```

---

## 📝 Document Structure
The generated document follows a standard professional template:
1.  **Heading**: [Ticket ID] - [Topic] 
2.  **Task Detail Table**: Includes Ticket No, Description, Date, and Author (Extracted from branch).
3.  **Changes Done**: High-level affected modules and brief AI-generated bullet points.
4.  **Test Cases Table**: A 3-column grid (Index, Case, Status) verifying the fix.
5.  **Screenshots**: Smartly positioned images with Test Case sub-headings.
