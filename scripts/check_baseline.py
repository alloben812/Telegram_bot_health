from __future__ import annotations

"""Minimal baseline checks for local development.

This script is intentionally lightweight:
- parses project Python files without writing .pyc files;
- imports key modules without starting the bot or calling external APIs.
"""

import ast
import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXCLUDED_DIRS = {".git", ".garth_cache", "__pycache__", "venv", ".venv"}
KEY_MODULES = (
    "config",
    "security",
    "database.models",
    "database.db",
    "integrations.garmin",
    "integrations.whoop",
    "training.planner",
    "bot.main",
)


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.py"):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def check_parse() -> None:
    for path in iter_python_files():
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
    print(f"Parsed {len(iter_python_files())} Python files")


def check_imports() -> None:
    for module_name in KEY_MODULES:
        importlib.import_module(module_name)
    print(f"Imported {len(KEY_MODULES)} key modules")


def main() -> None:
    check_parse()
    check_imports()
    print("Baseline checks passed")


if __name__ == "__main__":
    main()
