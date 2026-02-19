#!/usr/bin/env bash
# exit on error
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers (chromium only to save time/space)
playwright install chromium
playwright install-deps chromium
