#!/usr/bin/env python3
"""Determinism-boundary gate (WP-A1b amendment 10 / §4.3) — no network import in any green-gate module.

The @live lane (a real model call) is irreducibly non-deterministic and lives OUT of the green gate: CI and
pytest only REPLAY committed bytes, with no network and no API key. The external review flagged that a
runtime ``sys.modules`` guard is necessary-but-NOT-sufficient (it misses a lazy/dynamic import on an
un-exercised path). So this STATIC gate AST-parses every module under ``core/`` and ``scripts/`` (the
green-gate + replay surface) and fails closed if any of them imports a network library — by a static
``import``/``from`` OR a literal ``importlib.import_module("...")`` / ``__import__("...")``.

The ONLY modules permitted to touch the network are the designated ``live``-lane modules (``core/live_client``,
``scripts/agent_live_capture``) — which are never imported by a test or a gate and are out of the green gate.
They do not exist yet (the live call is deferred); they are allowlisted BY PATH so a future live module is
exempt deliberately, not by accident, and every other green module stays provably network-free.

Denylist precision: ``urllib.request`` / ``http.client`` (network) are flagged but ``urllib.parse`` /
``http.HTTPStatus`` (no network) are not, so the gate has no false positive on legitimate stdlib use.

Exit codes: 0 = clean, 1 = a network import found in a green module, 2 = a module could not be parsed
(fail-closed) or the scan dirs are missing.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("core", "scripts")

# Network-performing modules (dotted prefixes). A module is flagged iff its dotted import path equals one of
# these or is a submodule of one. urllib.parse / http (HTTPStatus) are intentionally absent (no network).
NETWORK_MODULES = (
    "anthropic", "httpx", "requests", "urllib3", "aiohttp", "socket",
    "urllib.request", "http.client", "live_client", "core.live_client",
)
# The @live lane — the sole network-permitted modules, exempt BY PATH (repo-relative). Deferred / absent today.
LIVE_ALLOWLIST = frozenset({"core/live_client.py", "scripts/agent_live_capture.py"})


def _denylisted(dotted: str) -> str | None:
    """The denylist entry a dotted import path violates, or None. Submodule-aware, sibling-safe
    (``urllib.request`` flags ``urllib.request``/``urllib.request.x`` but never ``urllib.parse``)."""
    for d in NETWORK_MODULES:
        if dotted == d or dotted.startswith(d + "."):
            return d
    return None


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Every (lineno, dotted_module) an AST imports — static import/from + literal dynamic import."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # relative (from . import x) — intra-package, never network
                continue
            base = node.module or ""
            found.append((node.lineno, base))
            for alias in node.names:  # `from urllib import request` -> the module urllib.request
                found.append((node.lineno, f"{base}.{alias.name}" if base else alias.name))
        elif isinstance(node, ast.Call):
            fn = node.func
            is_import_call = (isinstance(fn, ast.Name) and fn.id == "__import__") or (
                isinstance(fn, ast.Attribute) and fn.attr == "import_module")
            if is_import_call and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.append((node.lineno, node.args[0].value))
    return found


def scan(root: Path) -> list[tuple[str, int, str, str]]:
    """Return (relpath, lineno, dotted, denylist_entry) for every network import in a green module.
    Raises RuntimeError if a scan dir is missing or a file cannot be parsed (fail-closed)."""
    findings: list[tuple[str, int, str, str]] = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            raise RuntimeError(f"scan dir {d}/ is missing under {root}")
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in LIVE_ALLOWLIST:
                continue
            try:
                tree = ast.parse(path.read_bytes(), filename=rel)
            except (SyntaxError, ValueError) as exc:
                raise RuntimeError(f"{rel}: could not parse ({exc})") from exc
            for lineno, dotted in _imports(tree):
                hit = _denylisted(dotted)
                if hit is not None:
                    findings.append((rel, lineno, dotted, hit))
    return findings


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="validate_no_network_imports.py",
                            description="Fail closed if a green-gate module imports a network library.").parse_args(argv)
    try:
        findings = scan(REPO_ROOT)
    except RuntimeError as exc:
        print(f"error: {exc}; refusing to report clean.", file=sys.stderr)
        return 2
    if findings:
        print(f"no-network-imports gate FAILED: {len(findings)} network import(s) in green modules:", file=sys.stderr)
        for rel, lineno, dotted, hit in findings:
            print(f"  - network-import  {rel}:{lineno}  imports {dotted!r} (denylisted: {hit!r})", file=sys.stderr)
        print("  green-gate/replay modules must be network-free; the @live lane is the only exception "
              f"(allowlist: {sorted(LIVE_ALLOWLIST)}).", file=sys.stderr)
        return 1
    print(f"no-network-imports OK (core/ + scripts/ are network-free; live allowlist {sorted(LIVE_ALLOWLIST)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
