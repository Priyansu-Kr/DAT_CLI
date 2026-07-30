#!/bin/bash

# DAT_CLI Universal Auto-Setup Script (Mac & Linux)
echo "🚀 Starting DAT_CLI Setup..."

# Detect OS
OS="$(uname)"
SHELL_CONFIG="$HOME/.bashrc"
if [ "$OS" == "Darwin" ]; then
    echo "🍎 Mac detected..."
    SHELL_CONFIG="$HOME/.zshrc"
elif [ "$OS" == "Linux" ]; then
    echo "🐧 Linux detected..."
    # Install dependencies for Linux
    sudo apt update && sudo apt install -y python3-venv python3-tk
else
    echo "⚠️ Unknown OS. Attempting standard setup..."
fi

# 1. Create Virtual Environment
echo "🐍 Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 2. Install DAT_CLI and its requirements
echo "🛠 Installing DAT_CLI..."
pip install --upgrade pip
pip install -e .
pip install requests pillow python-docx pyyaml rich

# 3. Create the 'dat' command shortcut
echo "🔗 Creating 'dat' command shortcut in $SHELL_CONFIG..."
# Remove any existing alias to avoid duplicates
if [ -f "$SHELL_CONFIG" ]; then
    sed -i '' '/alias dat=/d' "$SHELL_CONFIG" 2>/dev/null || sed -i '/alias dat=/d' "$SHELL_CONFIG"
fi
# Add the new absolute path alias
echo "alias dat='$(pwd)/venv/bin/dat'" >> "$SHELL_CONFIG"

echo "✅ Setup Complete!"
echo "⚠️  ACTION REQUIRED: Run 'source $SHELL_CONFIG' or restart your terminal."
echo "🎯 Then you can run 'dat generate-doc -s' from any project folder (Android, iOS, Web, etc.)."
