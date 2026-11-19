"""Read-only access to the repository's files, for the studio's file viewer and guide images.

A path from the browser is never joined to the file system as given. `clean` accepts a
repository-relative POSIX path only: no absolute paths, no drive letters, no backslashes,
no `.` or `..` segments, nothing hidden (`.git`, `.env`, `.venv`, `.studio`), and the
first segment must be one of a few known directories or root files. `resolve` then
follows symlinks and checks that the real path is still inside the repository and passes
the same rules, so a link cannot lead out of it or into a hidden directory.

The studio's own lesson definitions are left out: they hold the reference solutions, which
the studio shows only after a first attempt.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ALLOWED_DIRS = ("guide", "src", "exercises", "solutions", "tests", "tools", "docs")
ALLOWED_FILES = (
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "Makefile",
    "docker-compose.yml",
    "pyproject.toml",
)
#: inside an allowed directory, but not shown (the studio's exercise solutions)
EXCLUDED = ("src/nosqlde/studio/lessons",)
SKIP_PARTS = frozenset({"__pycache__", "node_modules"})
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
MAX_BYTES = 300_000
MAX_ENTRIES = 500


class FileRefused(Exception):
    """A path the viewer will not show. `status` is the HTTP status to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def clean(rel: str) -> str:
    """The normalised repository-relative path, or FileRefused(400)."""
    if not rel or len(rel) > 400 or "\x00" in rel or "\\" in rel:
        raise FileRefused(400, "Only files inside the repository can be shown.")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or rel.startswith("~"):
        raise FileRefused(400, "Only files inside the repository can be shown.")
    rel = rel[:-1] if rel.endswith("/") else rel
    parts = rel.split("/")
    for part in parts:
        if part in ("", ".", "..") or part.startswith(".") or part in SKIP_PARTS:
            raise FileRefused(400, "Only files inside the repository can be shown.")
    if parts[0] not in ALLOWED_DIRS and rel not in ALLOWED_FILES:
        raise FileRefused(400, "Only the guide, the code, the exercises and the docs can be shown.")
    if any(rel == x or rel.startswith(x + "/") for x in EXCLUDED):
        raise FileRefused(
            403, "The studio's lesson files hold the exercise solutions; they open after an attempt."
        )
    return rel


def resolve(rel: str, root: Path) -> tuple[str, Path]:
    """(clean path, real path) of an existing file or directory inside `root`."""
    rel = clean(rel)
    base = root.resolve()
    try:
        real = (base / rel).resolve(strict=True)
    except (OSError, RuntimeError) as err:
        raise FileRefused(404, f"No such file in the repository: {rel}") from err
    try:
        inside = real.relative_to(base)
    except ValueError as err:
        raise FileRefused(400, "Only files inside the repository can be shown.") from err
    clean(inside.as_posix())  # a symlink must not lead somewhere the rules above refuse
    return rel, real


def viewable(rel: str, root: Path) -> bool:
    try:
        resolve(rel, root)
    except FileRefused:
        return False
    return True


def read(rel: str, root: Path) -> dict[str, Any]:
    """A file's text, or a directory's entries, for the viewer."""
    rel, real = resolve(rel, root)
    if real.is_dir():
        entries = []
        for child in sorted(real.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            path = f"{rel}/{child.name}"
            if viewable(path, root):
                entries.append(
                    {"name": child.name, "path": path, "kind": "dir" if child.is_dir() else "file"}
                )
            if len(entries) >= MAX_ENTRIES:
                break
        return {"path": rel, "kind": "dir", "entries": entries}
    if not real.is_file():
        raise FileRefused(404, f"No such file in the repository: {rel}")
    size = real.stat().st_size
    if size > MAX_BYTES:
        raise FileRefused(413, f"{rel} is {size:,} bytes; the viewer shows files up to {MAX_BYTES:,}.")
    data = real.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as err:
        raise FileRefused(415, f"{rel} is not a text file.") from err
    if "\x00" in text:
        raise FileRefused(415, f"{rel} is not a text file.")
    return {
        "path": rel,
        "kind": "file",
        "text": text,
        "lines": text.count("\n") + (0 if text.endswith("\n") or not text else 1),
        "bytes": size,
    }


def image(rel: str, root: Path) -> tuple[Path, str]:
    """(real path, media type) of an image under guide/ or docs/, else FileRefused."""
    rel, real = resolve(rel, root)
    media = IMAGE_TYPES.get(real.suffix.lower())
    if media is None or not real.is_file() or rel.split("/")[0] not in ("guide", "docs"):
        raise FileRefused(404, "No such image.")
    return real, media
