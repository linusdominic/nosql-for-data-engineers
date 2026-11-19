"""Where the studio finds the repository (guide/, exercises/, lake/) and keeps progress."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """NOSQLDE_ROOT, else the current directory if it is the repository, else the
    checkout this package was installed from (src/nosqlde/studio -> repository)."""
    env = os.environ.get("NOSQLDE_ROOT")
    if env:
        return Path(env)
    cwd = Path.cwd()
    if (cwd / "exercises").is_dir() and (cwd / "guide").is_dir():
        return cwd
    return Path(__file__).resolve().parents[3]


def progress_file() -> Path:
    return repo_root() / ".studio" / "progress.json"
