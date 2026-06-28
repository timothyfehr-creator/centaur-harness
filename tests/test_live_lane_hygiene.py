"""WP-A1b live-lane hygiene: the CAPTURE_ARTIFACT label exists + the key/spend-ledger/raw-wire paths are
git-ignored (so a live capture cannot commit the api-key, the spend ledger, or prose-bearing raw bytes)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from validate_schemas import WORLD_VS_GAME_LABELS  # noqa: E402


def test_capture_artifact_label_registered() -> None:
    # the deflationary live-capture label, distinct from the shared ILLUSTRATIVE
    assert "CAPTURE_ARTIFACT" in WORLD_VS_GAME_LABELS


def _ignored(rel: str) -> bool:
    return subprocess.run(["git", "-C", str(REPO_ROOT), "check-ignore", "-q", rel]).returncode == 0


def test_key_spend_ledger_and_raw_wire_are_gitignored() -> None:
    assert _ignored(".env")                                          # the api-key file
    assert _ignored("examples/x/run/llm_spend.local.json")          # the run-local spend ledger
    assert _ignored("anything.local.json")
    assert _ignored("live_raw/wire.json")                           # stray raw wire (carries prose)
    assert _ignored("examples/x/live_raw/wire.json")
    # ...but a normal committed (redacted) response artifact is NOT ignored
    assert not _ignored("examples/x/run/llm/abc123.json")
