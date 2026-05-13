#!/usr/bin/env bash
set -e

# Python dependencies
pip install -r requirements.txt

# Playwright browsers in project venv speichern (damit sie deployed werden)
export PLAYWRIGHT_BROWSERS_PATH=0

# Install Playwright Chromium (headless shell wird automatisch mitinstalliert)
python -m playwright install chromium
