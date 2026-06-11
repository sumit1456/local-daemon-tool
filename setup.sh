#!/bin/bash
# setup.sh — One-time setup for Code Search Engine (Linux/Mac)
# Creates venvs, installs all dependencies.

set -e
cd "$(dirname "$0")"

echo ""
echo "  ===================================="
echo "   Code Search Engine - Setup"
echo "  ===================================="
echo ""

# ── Check Python ──────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "  ERROR: python3 not found."
    echo "  Install Python 3.11+:"
    echo "    Ubuntu/Debian: sudo apt install python3 python3-venv"
    echo "    Mac: brew install python@3.11"
    exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "  Found python3 $PYVER"

# ── Create main venv ──────────────────────────────────────────────────────
if [ ! -f ".venv/bin/python" ]; then
    echo ""
    echo "  Creating main virtual environment..."
    python3 -m venv .venv
    echo "  .venv created."
else
    echo "  .venv already exists, skipping creation."
fi

# ── Install main dependencies ─────────────────────────────────────────────
echo ""
echo "  Installing main dependencies..."
.venv/bin/pip install --upgrade pip >/dev/null 2>&1
.venv/bin/pip install -r requirements.txt

# ── Create MCP venv ───────────────────────────────────────────────────────
if [ ! -f ".venv-mcp/bin/python" ]; then
    echo ""
    echo "  Creating MCP server virtual environment..."
    python3 -m venv .venv-mcp
    .venv-mcp/bin/pip install --upgrade pip >/dev/null 2>&1
    .venv-mcp/bin/pip install mcp httpx
    echo "  .venv-mcp created."
else
    echo "  .venv-mcp already exists, skipping creation."
fi

# ── Done ──────────────────────────────────────────────────────────────────
echo ""
echo "  ===================================="
echo "   Setup complete!"
echo "  ===================================="
echo ""
echo "  Next steps:"
echo "    1. Run:  ./CodeEngine.sh"
echo "    2. Or:   .venv/bin/python launcher.pyw"
echo ""
