#!/bin/bash
# CodeEngine.sh — Launch Code Search Engine (Linux/Mac)
# Uses python (not pythonw) since Linux/Mac don't have pythonw.

cd "$(dirname "$0")"
.venv/bin/python launcher.pyw
