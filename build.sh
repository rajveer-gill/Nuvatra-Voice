#!/bin/bash
# Force Railway to rebuild with correct versions
set -e

echo "=== FORCING CLEAN INSTALL ==="
echo "Removing any cached packages..."
pip cache purge || true

echo "Installing requirements..."
cd backend
pip install --no-cache-dir --upgrade pip
pip install --no-cache-dir -r requirements.txt

echo "=== VERIFYING INSTALLED VERSIONS ==="
pip show openai httpx | grep -E "Name:|Version:"

echo "=== BUILD COMPLETE ==="


