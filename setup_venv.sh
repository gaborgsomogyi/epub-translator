#!/bin/bash
set -e

echo "Setting up Python 3.13 virtual environment..."

if ! command -v python3.13 &>/dev/null; then
    echo "Python 3.13 not found. Please install it first."
    echo "  Ubuntu/Debian: sudo apt install python3.13 python3.13-venv"
    echo "  Fedora:        sudo dnf install python3.13"
    echo "  macOS:         brew install python@3.13"
    exit 1
fi

python3.13 -m venv .venv
source .venv/bin/activate
pip install -e .

echo ""
echo "Done! Virtual environment is ready and activated."
echo "To activate it in a new terminal, run: source .venv/bin/activate"
