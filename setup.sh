#!/usr/bin/env bash
set -e

echo "🐟 FishY — Setup"

# Install Python deps
pip3 install -r requirements.txt

# Install playwright browsers
python3 -m playwright install chromium 2>/dev/null || playwright install chromium 2>/dev/null || true

# Install system deps
if [[ "$OSTYPE" == "darwin"* ]]; then
  brew install wget cloudflared 2>/dev/null || true
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
  sudo apt install wget -y 2>/dev/null || true
  # install cloudflared
  if ! command -v cloudflared &>/dev/null; then
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cfd && chmod +x /tmp/cfd && sudo mv /tmp/cfd /usr/local/bin/cloudflared 2>/dev/null || true
  fi
fi

echo ""
echo "✅ Done! Run: python3 app.py"
