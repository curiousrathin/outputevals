"""The skill library: Markdown and text files on disk, one folder per skill.

Files are real files so they can be edited anywhere (VS Code, Claude Code) and
versioned with git. Configurations attach folders or single files; a folder
attachment is resolved when each run starts, and every trial records the
content hash of each file the model saw, so a run is reproducible even after
the files change.

Every path goes through `resolve`, which keeps it inside the library: no
absolute paths, no "..", no hidden files, no symlinks.
"""

import hashlib
from pathlib import Path, PurePosixPath

from app.config import settings

ALLOWED_SUFFIXES = (".md", ".txt")
MAX_FILE_BYTES = 200_000


class LibraryError(ValueError):
    pass


def root() -> Path:
    path = settings.library_dir or settings.data_dir / "library"
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def normalize(rel: str) -> str:
    """A clean relative path with forward slashes, or LibraryError."""
    raw = (rel or "").strip().replace("\\", "/")
    if raw.startswith("/") or ":" in raw:  # absolute or drive-letter paths
        raise LibraryError(f"Invalid library path: {rel!r}")
    parts = PurePosixPath(raw.rstrip("/")).parts
    if not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
        raise LibraryError(f"Invalid library path: {rel!r}")
    return "/".join(parts)


def resolve(rel: str) -> Path:
    base = root()
    path = base / normalize(rel)
    if path.is_symlink() or not path.resolve().is_relative_to(base):
        raise LibraryError(f"Invalid library path: {rel!r}")
    return path


def _visible(path: Path, base: Path) -> bool:
    rel = path.relative_to(base)
    return not path.is_symlink() and not any(p.startswith(".") for p in rel.parts)


def _is_doc(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in ALLOWED_SUFFIXES


def tree() -> list[dict]:
    """Folders first, then SKILL.md, then other files, alphabetically. Only .md/.txt files are listed."""
    base = root()

    def order(p: Path):
        return (p.is_file(), p.name.lower() != "skill.md", p.name.lower())

    def walk(folder: Path) -> list[dict]:
        items = []
        for p in sorted(folder.iterdir(), key=order):
            if not _visible(p, base):
                continue
            rel = p.relative_to(base).as_posix()
            if p.is_dir():
                items.append({"path": rel, "name": p.name, "type": "folder", "children": walk(p)})
            elif _is_doc(p):
                items.append({"path": rel, "name": p.name, "type": "file", "size": p.stat().st_size})
        return items

    return walk(base)


def read_file(rel: str) -> str:
    path = resolve(rel)
    if not _is_doc(path):
        raise LibraryError(f"No library file at {rel!r}.")
    return path.read_text(encoding="utf-8", errors="replace")


def write_file(rel: str, content: str) -> None:
    path = resolve(rel)
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise LibraryError("Library files must end in .md or .txt.")
    if path.is_dir():
        raise LibraryError(f"{rel!r} is a folder.")
    if len(content.encode()) > MAX_FILE_BYTES:
        raise LibraryError(f"Files are limited to {MAX_FILE_BYTES // 1000} KB. Split it into smaller files.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_folder(rel: str) -> None:
    path = resolve(rel)
    if path.exists():
        raise LibraryError(f"{rel!r} already exists.")
    path.mkdir(parents=True)


def delete(rel: str) -> None:
    path = resolve(rel)
    if path.is_dir():
        if any(path.iterdir()):
            raise LibraryError("Only empty folders can be deleted. Delete or move its files first.")
        path.rmdir()
    elif _is_doc(path):
        path.unlink()
    else:
        raise LibraryError(f"No library item at {rel!r}.")


def validate_attachments(paths: list[str]) -> list[str]:
    """Normalized, de-duplicated attachment paths that exist right now."""
    clean = []
    for rel in paths:
        norm = normalize(rel)
        path = resolve(norm)
        if not (path.is_dir() or _is_doc(path)):
            raise LibraryError(f"Can't attach {rel!r}: it isn't a folder or a .md/.txt file in the library.")
        if norm not in clean:
            clean.append(norm)
    return clean


def resolve_attachments(paths: list[str]) -> list[dict]:
    """Expand attachments into the files a run will see: [{path, text, sha256}].

    Folders expand to every .md/.txt file inside them, at the moment of the run.
    A missing attachment raises instead of being skipped, so an experiment never
    silently loses context."""
    base = root()
    files: dict[str, dict] = {}
    for rel in paths:
        path = resolve(rel)
        if path.is_dir():
            found = sorted(f for f in path.rglob("*") if _visible(f, base) and _is_doc(f))
        elif _is_doc(path):
            found = [path]
        else:
            raise LibraryError(
                f"This configuration attaches {rel!r}, which no longer exists in the library. "
                "Restore it, or edit the configuration to remove it."
            )
        for f in found:
            key = f.relative_to(base).as_posix()
            if key not in files:
                text = f.read_text(encoding="utf-8", errors="replace")
                files[key] = {
                    "path": key,
                    "text": text,
                    "sha256": hashlib.sha256(text.encode()).hexdigest()[:12],
                }
    return list(files.values())


def is_used_by(attachment: str, target: str) -> bool:
    """Would deleting `target` remove the attached path?"""
    return attachment == target or attachment.startswith(f"{target}/")
