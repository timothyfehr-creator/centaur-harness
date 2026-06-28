"""The determinism boundary (WP-A1b §4.3): green-gate/replay modules never touch the network.

Two complementary checks: a STATIC AST scan (validate_no_network_imports — catches a lazy/dynamic import on
an un-exercised path) and a RUNTIME sys.modules guard (no network SDK is pulled in by importing the gate +
replay modules). The @live lane is deferred; until it exists, core/ + scripts/ must be entirely network-free.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GATE = REPO_ROOT / "scripts" / "validate_no_network_imports.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "core"))

import validate_no_network_imports as nni  # noqa: E402


def test_repo_green_modules_are_network_free() -> None:
    r = subprocess.run([sys.executable, str(GATE)], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert nni.scan(REPO_ROOT) == []


def _tmp_repo(tmp: Path, files: dict) -> Path:
    root = tmp / "repo"
    for d in ("core", "scripts"):
        (root / d).mkdir(parents=True)
    for rel, src in files.items():
        (root / rel).write_text(src, encoding="utf-8")
    return root


def test_scan_catches_a_static_network_import(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, {"core/bad.py": "import socket\n", "scripts/ok.py": "import json\n"})
    findings = nni.scan(root)
    assert len(findings) == 1 and findings[0][0] == "core/bad.py" and findings[0][3] == "socket"


def test_scan_catches_literal_dynamic_import(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, {"core/dyn.py": "import importlib\nx = importlib.import_module('anthropic')\n",
                                "scripts/dyn2.py": "y = __import__('requests')\n"})
    hits = {f[3] for f in nni.scan(root)}
    assert hits == {"anthropic", "requests"}


def test_no_false_positive_on_non_network_stdlib(tmp_path: Path) -> None:
    # urllib.parse / http (HTTPStatus) do no network -- they must NOT be flagged, or the gate is useless noise.
    root = _tmp_repo(tmp_path, {"core/parse.py": "import urllib.parse\nfrom http import HTTPStatus\n",
                                "scripts/ok.py": "from urllib.parse import quote\n"})
    assert nni.scan(root) == []


def test_from_import_of_network_submodule_is_caught(tmp_path: Path) -> None:
    root = _tmp_repo(tmp_path, {"core/a.py": "from urllib import request\n",
                                "scripts/b.py": "from http import client\n"})
    hits = {f[3] for f in nni.scan(root)}
    assert hits == {"urllib.request", "http.client"}


def test_unparseable_module_fails_closed(tmp_path: Path) -> None:
    import pytest
    root = _tmp_repo(tmp_path, {"core/broken.py": "def (:\n"})
    with pytest.raises(RuntimeError):
        nni.scan(root)


def test_runtime_sysmodules_guard_no_network_sdk() -> None:
    # importing the gate + replay surface must not pull a network SDK into the process (the complement to
    # the static scan: proves the import graph that CI/pytest actually executes stays network-free).
    for mod in ("validate_agent_provenance", "validate_turn_replay", "validate_agent_fog",
                "agent_offline_run", "command_extractor", "prompt_templates", "response_redact"):
        __import__(mod)
    forbidden = {"anthropic", "httpx", "requests", "urllib3", "aiohttp", "live_client", "core.live_client"}
    assert forbidden.isdisjoint(sys.modules), forbidden & sys.modules.keys()
