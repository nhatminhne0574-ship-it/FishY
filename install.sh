#!/bin/bash
set -e

APP_NAME="FishY"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/$APP_NAME"
APPLICATIONS_DIR="$HOME/.local/share/applications"
ICONS_DIR="$HOME/.local/share/icons"

echo ""
echo "  🐟 Installing $APP_NAME..."
echo ""

# Check wget
if ! command -v wget &> /dev/null; then
    echo "  ❌ wget is not installed!"
    echo "     Install it: sudo apt install wget"
    exit 1
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  ❌ Python 3 is not installed!"
    exit 1
fi

# Install Python deps if needed
for pkg in flask pywebview playwright; do
    if ! python3 -c "import $pkg" 2>/dev/null; then
        echo "  📦 Installing $pkg..."
        pip3 install --break-system-packages "$pkg" 2>/dev/null || pip3 install "$pkg" 2>/dev/null || {
            echo "  ⚠️  Could not install $pkg. Install manually: pip3 install $pkg"
        }
    fi
done

# Install Playwright browsers if playwright is installed
if python3 -c "import playwright" 2>/dev/null; then
    if [ ! -d "$HOME/.cache/ms-playwright/chromium-"* ] 2>/dev/null; then
        echo "  🌐 Installing Playwright Chromium..."
        python3 -m playwright install chromium 2>/dev/null || true
    fi
fi

# Create directories
mkdir -p "$INSTALL_DIR"
mkdir -p "$APPLICATIONS_DIR"
mkdir -p "$ICONS_DIR"

# Copy app files
echo "  📁 Copying files..."
cp -r "$APP_DIR"/* "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/fishy"
chmod +x "$INSTALL_DIR/fishy.py"

# Install desktop file
echo "  📋 Installing desktop entry..."
sed "s|__INSTALL_DIR__|$INSTALL_DIR|g" "$APP_DIR/FishY.desktop" > "$APPLICATIONS_DIR/FishY.desktop"
chmod +x "$APPLICATIONS_DIR/FishY.desktop"

# Install icon
echo "  🖼️  Installing icon..."
cp "$APP_DIR/icon.svg" "$ICONS_DIR/FishY.svg"

# Update desktop database
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$APPLICATIONS_DIR" 2>/dev/null || true
fi

echo ""
echo "  ✅ $APP_NAME installed!"
echo ""
echo "  📍 App:  $INSTALL_DIR"
echo "  🔗 Run:  $INSTALL_DIR/fishy"
echo ""
echo "  Look for FishY in your app menu or run it from the terminal."
echo ""
