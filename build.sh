#!/usr/bin/env bash
set -e

# System dependencies for Playwright on Ubuntu/Debian
apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm-dev libxkbcommon-dev \
    libgbm-dev libasound2 libxshmfence-dev

# Python dependencies
pip install -r requirements.txt

# Install Playwright browser
python -m playwright install chromium
python -m playwright install-deps chromium
