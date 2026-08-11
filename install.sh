#!/bin/bash
# DAT_CLI installer for the PyPI package (Mac & Linux).
#
# This is the counterpart to setup.sh: setup.sh builds DAT from a git clone,
# this one installs the published package and fixes up the two things pip
# cannot do by itself — the system Tk libraries and your PATH.
#
#   curl -fsSL https://raw.githubusercontent.com/Priyansu-Kr/DAT_CLI/main/install.sh -o install.sh
#   bash install.sh

set -u

PACKAGE="developer-automation-toolkit"

echo "🚀 Installing DAT_CLI from PyPI..."

# ---------------------------------------------------------------- 1. Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 not found. Install Python 3.9+ and re-run this script."
    exit 1
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo "❌ Python 3.9+ required, found $(python3 -V)."
    exit 1
fi
echo "🐍 Using $(python3 -V)"

# ------------------------------------------------------- 2. Tk system libs
# The Preview Panel is a Tk GUI. tkinter ships with the OS Python packaging,
# never from PyPI, so pip alone leaves you with an import error at runtime.
# PIL.ImageTk is the second half of the same story: distros split Pillow's Tk
# bridge into its own package, and without it the preview renders every
# screenshot as "[image unavailable]" while the exported .docx looks fine.
install_tk() {
    case "$(uname)" in
        Darwin)
            if command -v brew >/dev/null 2>&1; then
                brew list python-tk >/dev/null 2>&1 || brew install python-tk
            else
                echo "⚠️  Homebrew not found — install Tk manually if the GUI fails to start."
            fi
            ;;
        Linux)
            if command -v apt-get >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y python3-tk python3-pil.imagetk
            elif command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y python3-tkinter python3-pillow-tk
            elif command -v pacman >/dev/null 2>&1; then
                sudo pacman -S --noconfirm tk python-pillow
            else
                echo "⚠️  Unknown package manager — install the python3-tk and python3-pil.imagetk packages manually."
            fi
            ;;
        *)
            echo "⚠️  Unrecognised OS: $(uname). Skipping Tk setup."
            ;;
    esac
}

if python3 -c "import tkinter; from PIL import ImageTk" >/dev/null 2>&1; then
    echo "🖼  Tkinter and Pillow's ImageTk already present."
else
    echo "🖼  Installing Tk system libraries..."
    install_tk
fi

# ------------------------------------------------------------ 3. The package
echo "📦 Installing $PACKAGE..."
if ! python3 -m pip install --user --upgrade "$PACKAGE"; then
    # Debian/Ubuntu 23.04+ and Homebrew Python mark site-packages as
    # externally managed (PEP 668) and refuse --user installs outright.
    if command -v pipx >/dev/null 2>&1; then
        echo "↩️  pip refused; falling back to pipx..."
        pipx install "$PACKAGE" || exit 1
    else
        echo ""
        echo "❌ pip could not install into your user site-packages."
        echo "   Your Python is 'externally managed' (PEP 668). Pick one:"
        echo "     sudo apt install pipx && pipx install $PACKAGE"
        echo "   or install into a virtual environment:"
        echo "     python3 -m venv ~/.dat-venv && ~/.dat-venv/bin/pip install $PACKAGE"
        exit 1
    fi
fi

# ---------------------------------------------------------------- 4. PATH
BIN_DIR="$(python3 -m site --user-base)/bin"

case "$(basename "${SHELL:-bash}")" in
    zsh)  SHELL_CONFIG="$HOME/.zshrc" ;;
    bash) [ "$(uname)" == "Darwin" ] && SHELL_CONFIG="$HOME/.bash_profile" || SHELL_CONFIG="$HOME/.bashrc" ;;
    *)    SHELL_CONFIG="$HOME/.profile" ;;
esac

if command -v dat >/dev/null 2>&1; then
    echo "🔗 'dat' is already on your PATH."
    NEEDS_RELOAD=0
elif [ -x "$BIN_DIR/dat" ]; then
    echo "🔗 Adding $BIN_DIR to PATH in $SHELL_CONFIG..."
    # Idempotent: drop any line this script added before re-adding it.
    if [ -f "$SHELL_CONFIG" ]; then
        sed -i '' '/# added by DAT_CLI install.sh/d' "$SHELL_CONFIG" 2>/dev/null \
            || sed -i '/# added by DAT_CLI install.sh/d' "$SHELL_CONFIG"
    fi
    echo "export PATH=\"$BIN_DIR:\$PATH\" # added by DAT_CLI install.sh" >> "$SHELL_CONFIG"
    export PATH="$BIN_DIR:$PATH"
    NEEDS_RELOAD=1
else
    echo "⚠️  Installed, but no 'dat' launcher found in $BIN_DIR."
    NEEDS_RELOAD=0
fi

# --------------------------------------------------------------- 5. Verify
echo ""
if command -v dat >/dev/null 2>&1; then
    echo "🩺 Running environment check..."
    dat doctor
else
    echo "⚠️  Could not run 'dat' in this shell yet — reload your shell and try 'dat doctor'."
fi

echo ""
echo "✅ Setup complete!"
if [ "$NEEDS_RELOAD" == "1" ]; then
    echo "⚠️  ACTION REQUIRED: run 'source $SHELL_CONFIG' or open a new terminal."
fi
echo "🎯 Then, from any git project folder:  dat generate-doc -s"
