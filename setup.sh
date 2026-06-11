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

# ── Find Python 3.10+ ─────────────────────────────────────────────────────
find_python() {
    # Try versioned names first (most reliable on servers)
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" &>/dev/null; then
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                echo "$cmd"
                return
            fi
        fi
    done
    echo ""
}

PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    echo "  ERROR: Python 3.10+ not found."
    echo ""
    echo "  Install it:"
    echo "    Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    echo "    RHEL/CentOS:   sudo dnf install python3.11"
    echo "    Mac:           brew install python@3.11"
    exit 1
fi

PYVER=$($PYTHON --version 2>&1 | awk '{print $2}')
echo "  Found $PYTHON $PYVER"

# ── Create main venv ──────────────────────────────────────────────────────
if [ ! -f ".venv/bin/python" ]; then
    echo ""
    echo "  Creating main virtual environment..."
    $PYTHON -m venv .venv
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
    $PYTHON -m venv .venv-mcp
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
