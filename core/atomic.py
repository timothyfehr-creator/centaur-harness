"""Atomic durable writes for engine artifacts (WP-E1) — persistence_profile local-posix-fs-v1.

``atomic_write`` replaces a file durably: write a temp file in the SAME directory, fsync it,
``os.replace`` into place, then fsync the PARENT directory (a file fsync alone does not make the
rename durable across power loss). ``commit_new_slot`` is the single-successor-per-head primitive:
create the slot with ``O_EXCL`` (never overwrite); if it already exists, require byte-identical
content (an idempotent retry) else fail closed.

Fault model: single-host process crash + power loss on a local POSIX filesystem. NOT multi-host /
network-fs (where rename atomicity and directory-fsync semantics differ). See docs/ENGINE_CONTRACT.md.
"""
from __future__ import annotations

import os
from pathlib import Path

PERSISTENCE_PROFILE = "local-posix-fs-v1"


class SlotConflict(RuntimeError):
    """A successor slot already exists with DIFFERENT bytes (not an idempotent retry)."""


def _fsync_dir(dirpath: Path) -> None:
    fd = os.open(str(dirpath), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path: str | os.PathLike, data: bytes) -> None:
    """Durably replace ``path`` with ``data`` (tmp-same-dir -> fsync -> os.replace -> fsync parent)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))   # atomic on a single filesystem
    _fsync_dir(path.parent)


def commit_new_slot(slot: str | os.PathLike, data: bytes) -> str:
    """Single-successor commit. Returns ``'committed'`` (created) or ``'idempotent'`` (already
    present, byte-identical). Raises ``SlotConflict`` if present with different bytes."""
    slot = Path(slot)
    slot.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(slot), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        if slot.read_bytes() == data:
            return "idempotent"
        raise SlotConflict(f"successor slot {slot} already committed with different bytes")
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(slot.parent)
    return "committed"
