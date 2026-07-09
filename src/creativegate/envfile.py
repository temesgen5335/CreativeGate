"""Minimal .env loader for local runs.

Design rationale: platforms inject real environment variables; local
developers keep a gitignored .env. This loader is invoked only from CLI
entrypoints — never on library/API import — so the test suite and any
embedding application are never surprised by a developer's local keys.
Existing environment variables always win over file values.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> int:
    """Load KEY=VALUE lines from a .env file into os.environ (no overrides).

    Returns the number of variables set. Missing file is not an error.
    """
    p = Path(path)
    if not p.is_file():
        return 0
    loaded = 0
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded
