#!/usr/bin/env bash
set -e

pip install -r requirements.txt

# Browser-Pfad innerhalb des Projekts (wird mit deployt)
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/.playwright

# Alten Build-Cache ignorieren, damit PLAYWRIGHT_BROWSERS_PATH wirkt
rm -rf /opt/render/.cache/ms-playwright 2>/dev/null || true

# Chromium + headless shell + FFmpeg frisch herunterladen
python -m playwright install chromium
