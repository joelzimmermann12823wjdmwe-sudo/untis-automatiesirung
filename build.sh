#!/usr/bin/env bash
set -e

# Python dependencies
pip install -r requirements.txt

# Install Playwright Chromium (system deps not available in build env)
python -m playwright install chromium chromium-headless-shell
