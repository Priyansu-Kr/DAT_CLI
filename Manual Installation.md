# Manual Installation Guide: DAT_CLI

If the automated `./setup.sh` script fails or you prefer a custom setup, follow these steps to install the Developer Automation Toolkit (DAT) manually.

---

## 📋 Step 1: System Requirements

### For Linux (Ubuntu/Debian)
Install Python, virtual environment support, and the UI library (Tkinter) needed for the file picker:
```bash
sudo apt update
sudo apt install python3 python3-venv python3-tk python3-pil.imagetk git -y
```

### For macOS
Ensure you have [Homebrew](https://brew.sh/) installed, then run:
```bash
brew install python tcl-tk
```

---

## 🐍 Step 2: Virtual Environment Setup

1.  **Navigate to the project root:**
    ```bash
    cd /path/to/DAT_CLI
    ```

2.  **Create the virtual environment:**
    ```bash
    python3 -m venv venv
    ```

3.  **Activate the environment:**
    - **Linux/macOS:** `source venv/bin/activate`
    - **Windows (Git Bash):** `source venv/Scripts/activate`

4.  **Install the package in editable mode:**
    ```bash
    pip install --upgrade pip
    pip install -e .
    ```

---

## 🔗 Step 3: Global Command Shortcut (Alias)

To run `dat` from any folder on your system without typing the full path:

1.  **Identify your shell config file:**
    - **Linux:** `~/.bashrc`
    - **macOS:** `~/.zshrc`

2.  **Add the alias:**
    Open the file in an editor (e.g., `nano ~/.zshrc`) and add this line at the bottom:
    ```bash
    alias dat='/FULL/PATH/TO/DAT_CLI/venv/bin/dat'
    ```
    *(Replace `/FULL/PATH/TO/` with the actual path to the folder on your computer).*

3.  **Refresh your terminal:**
    ```bash
    source ~/.bashrc  # or source ~/.zshrc
    ```

---

## 🔑 Step 4: AI Key Configuration (Optional)

DAT works without an API key: documents are then built from your Git diff, with
the changed file names as the "Changes Done" section and test cases left for you
to write.

To enable AI-written summaries instead, get a key from
[Google AI Studio](https://aistudio.google.com/app/apikey) and save it:

```bash
dat save-api-key    # prompts for the key and stores it in ~/.dat/config.yaml
```

Or keep it in your shell config, which DAT reads without ever writing it to disk:

```bash
echo 'export DAT_AI_KEY="YOUR_KEY_HERE"' >> ~/.zshrc # or .bashrc
source ~/.zshrc
```

---

## ✅ Step 5: Verification

Verify the installation by running:
```bash
dat doctor
```
If you see "ADB Available: OK" and "python-docx: OK", you are ready!

---

## 💡 Troubleshooting

### "ModuleNotFoundError: No module named '_tkinter'"
- **macOS:** Reinstall python with tk support: `brew uninstall python && brew install python && brew install tcl-tk`.
- **Linux:** Ensure you ran `sudo apt install python3-tk`.

### Preview shows "[image unavailable]" instead of screenshots
The exported `.docx` has the images but the on-screen preview does not. The
preview draws thumbnails through `PIL.ImageTk`, which Linux distros package
separately from Pillow; the DOCX writer never touches Tk, hence the split.
- **Linux:** `sudo apt install python3-pil.imagetk` (Fedora: `python3-pillow-tk`, Arch: `python-pillow`), then restart `dat`.
- **macOS / Windows:** `pip install --force-reinstall Pillow` — those wheels bundle ImageTk.

Confirm the fix with `python3 -c "from PIL import ImageTk"`; it should print nothing.

### "dat: command not found"
Ensure you ran the `source` command on your config file after adding the alias, or simply restart your terminal window.
