#!/usr/bin/env python3
"""Centaur agent-provenance validator (WP-A1a) — the H7 binding gate.

The offline agent substrate records a NON-CAUSAL `llm_steps` provenance list in each scenario's
run_ledger.yaml (one entry per (turn, slot) the agent boundary was called for). Because that block is
outside `transition_input_hash`, it has ZERO causal protection — so this gate is its integrity floor and is
MANDATORY in `release`. For every recorded step it asserts the model's SEMANTIC choice is bound to the
committed command, and that the command's IDENTITY was bound by the HARNESS, not authored by the model:

  Tier-1 (byte integrity): the content-addressed response bytes re-hash to the recorded `response_sha256`.
  Tier-2 (extractor dispatch): re-run the strict extractor on the recorded bytes (at the RECORDED
     extractor/canon version, or fail closed) → it reproduces the command (or the forfeit); the recorded
     `extracted_command_digest` must equal that recompute (the gate NEVER trusts the stored digest).
  H7a (semantic binding): canonical_digest(project_semantic(committed_command)) == that recompute.
  H7b (identity binding, three LITERAL asserts against harness-derived values): committed.actor_id ==
     calling_slot; committed.command_id == f"{run_id}:{turn}:{actor_id}"; committed.turn ==
     start_state.as_of_turn == turn_record.turn.
  Tier-3 (request-envelope binding, WP-A1b §2.3-2.4): for a step rendered from a REGISTERED + APPROVED
     prompt-template, RE-RENDER the request from the committed decision head's fog view and bind it by
     sha256 — catching a self-consistent request tamper (bytes re-hash fine but are not the render of the
     authorized template ∘ authorized fog view). An unknown / registered-but-unapproved version fails closed
     (exit 2). The OFFLINE synthetic envelope uses the reserved INTEGRITY_ONLY version (Tier-1 re-hash only).
     The binding is one leg of a THREE-LEGGED AND (binding ∘ fog no-leak ∘ template purity); alone it is NOT
     a no-leak proof — a leaky template binds green, which the audited allowlist + the purity invariant
     (prompt_templates) catch. BOUNDARY (amendment 6 / §2.5, disclosed): the binding binds the recorded
     CLIENT REQUEST BODY = render(prompt_version, fog_view) — CANONICAL content, not the provider's wire
     bytes; it EXCLUDES the api-key + TLS; provider-side tool scaffolding (Anthropic injects an automatic
     tool-use system prompt) is OUTSIDE the client request, assumed non-secret-bearing, NOT proven; and it
     holds only under no provider-side prompt caching carrying cross-turn state / no gateway-or-proxy context
     injection / no SDK-default system augmentation. It is tamper-evidence relative to a TRUSTED capture
     pipeline, not a defense against an adversary who controls capture (the authenticity residual).

STRUCTURE is the boundary (like validate_calibration_feasibility): unknown keys rejected at every level,
every field scalar, every enum pinned — so a tampered/identity-bearing step cannot ride along. A
self-consistent tamper (re-resolved record) passes turn-replay but FAILS here: only the binding to the
RECORDED BYTES catches that the committed command no longer matches what the bytes extract to.

STRUCTURAL + PROVENANCE ONLY: a clean result means the recorded steps are well-formed and bound to the
committed records + bytes, NOT that anything is analytically valid. Composed into `verify.py --mode release`.

Usage:
    python scripts/validate_agent_provenance.py                    # sweep examples/**/run_ledger.yaml
    python scripts/validate_agent_provenance.py --scenario-dir DIR # validate DIR/run_ledger.yaml's llm_steps

Exit codes: 0 = ok (steps bind, or none present), 1 = findings, 2 = usage / fail-closed (unreadable
scenario/ledger, or a recorded extractor/canon version this build cannot reproduce).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from canon import CANON_VERSION, canonical_digest  # noqa: E402
from command_extractor import (  # noqa: E402
    EXTRACTOR_VERSION,
    REJECT_CODES,
    extract_command,
    project_semantic,
)
from engine_projection import project_turn_record  # noqa: E402
from prompt_templates import (  # noqa: E402
    APPROVED_PROMPT_VERSIONS,
    PROMPT_TEMPLATES,
    canonical_request_bytes,
)
from validate_claims import load_registry  # noqa: E402
from validate_run_ledger import _sha256  # noqa: E402
from validate_schemas import REPO_ROOT, _display, _is_nonempty_str  # noqa: E402

CALLING_SLOT_ENUM = ("BLUE", "RED")
STEP_KIND_ENUM = ("COMMAND", "FORFEIT")
CAPTURE_MODE_ENUM = ("LIVE", "HAND_AUTHORED_FIXTURE")
PROVIDER_ENUM = ("anthropic",)
SAMPLING_ENUM = ("PROVIDER_DEFAULT_NO_SEED",)
FIXTURE_SENTINEL = "N/A_FIXTURE"   # model/model_version/served_model under HAND_AUTHORED_FIXTURE
# Reserved prompt_version(s) for the OFFLINE synthetic request envelope (_request_bytes): integrity-only,
# pre-template. A step on one of these is bound Tier-1 (the committed request bytes re-hash to the recorded
# sha — done above); no Tier-3 re-render. A registered TEMPLATE version triggers the re-render binding; any
# OTHER prompt_version is unknown -> fail closed (exit 2). (§2.3-2.4)
INTEGRITY_ONLY_PROMPT_VERSIONS = ("v1",)

# Unknown-key + scalar-only boundary: every llm_step field is a SCALAR (the only container is the
# llm_steps list itself), so a nested object cannot smuggle an un-vetted field past the gate.
ALLOWED_STEP = {"schema_version", "run_id", "turn", "recorded_turn", "calling_slot", "command_id",
                "step_kind", "capture_mode", "provider", "model", "model_version", "served_model",
                "sampling", "prompt_version", "extractor_version", "canon_version", "response_sha256",
                "request_envelope_sha256", "extracted_command_digest", "reject_code", "as_of"}
REQUIRED_STR = ("schema_version", "run_id", "command_id", "calling_slot", "step_kind", "capture_mode",
                "provider", "model", "model_version", "served_model", "sampling", "prompt_version",
                "extractor_version", "canon_version", "response_sha256", "request_envelope_sha256", "as_of")
_SCALAR = (str, int, float, bool, type(None))
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _fail_closed(reason: str) -> int:
    print(f"error: {reason}; refusing to report clean.", file=sys.stderr)
    return 2


def _report(problems: list[tuple[str, str, str]]) -> int:
    print(f"agent-provenance validation FAILED: {len(problems)} problem(s):", file=sys.stderr)
    for code, where, msg in problems:
        print(f"  - {code}  {where}  {msg}", file=sys.stderr)
    return 1


def _structural_problems(step: object, where: str) -> list[tuple[str, str, str]]:
    """Shape of ONE llm_step: mapping, unknown-key, scalar-only, required strings/ints, pinned enums, and
    the step_kind/capture_mode field-presence consistency. Returns findings (single-fault friendly)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    if not isinstance(step, dict):
        add("wrong-type", "llm_steps entry must be a mapping")
        return problems
    for k in step:
        if k not in ALLOWED_STEP:
            add("unknown-key", f"{k!r} is not an allowed llm_step key (allowed: {sorted(ALLOWED_STEP)})")
    for k, v in step.items():
        if not isinstance(v, _SCALAR):
            add("non-scalar-value", f"{k!r} must be a scalar (got {type(v).__name__})")
    if problems:
        return problems     # don't read fields off a structurally-broken step
    for f in REQUIRED_STR:
        if not _is_nonempty_str(step.get(f)):
            add("missing-field", f"{f} is required and must be a non-empty string")
    for f in ("turn", "recorded_turn"):
        if not isinstance(step.get(f), int) or isinstance(step.get(f), bool):
            add("missing-field", f"{f} is required and must be an integer")
    for f, enum in (("calling_slot", CALLING_SLOT_ENUM), ("step_kind", STEP_KIND_ENUM),
                    ("capture_mode", CAPTURE_MODE_ENUM), ("provider", PROVIDER_ENUM),
                    ("sampling", SAMPLING_ENUM)):
        if step.get(f) not in enum:
            add("invalid-enum", f"{f} must be one of {sorted(enum)}; got {step.get(f)!r}")
    if problems:
        return problems
    # version selectors must be reproducible by THIS build (a different version is fail-closed in binding).
    if step["canon_version"] != CANON_VERSION:
        add("canon-version-mismatch", f"canon_version {step['canon_version']!r} != {CANON_VERSION!r}")
    # recorded_turn is a redundant cross-check bound to turn (catches a misfiled step).
    if step["recorded_turn"] != step["turn"]:
        add("recorded-turn-mismatch", f"recorded_turn {step['recorded_turn']} != turn {step['turn']}")
    for f in ("response_sha256", "request_envelope_sha256"):
        if not _SHA256_RE.fullmatch(step[f]):
            add("invalid-format", f"{f} must be 64 lowercase hex; got {step[f]!r}")
    # HAND_AUTHORED_FIXTURE cannot claim a served model (honesty): the three model fields are pinned.
    if step["capture_mode"] == "HAND_AUTHORED_FIXTURE":
        for f in ("model", "model_version", "served_model"):
            if step[f] != FIXTURE_SENTINEL:
                add("fixture-model-claim",
                    f"{f} must be {FIXTURE_SENTINEL!r} under capture_mode HAND_AUTHORED_FIXTURE; got {step[f]!r}")
    # COMMAND <-> FORFEIT field presence: a COMMAND carries a digest + null reject_code; a FORFEIT the inverse.
    kind, digest, rc = step["step_kind"], step.get("extracted_command_digest"), step.get("reject_code")
    if kind == "COMMAND":
        if not (isinstance(digest, str) and _SHA256_RE.fullmatch(digest)):
            add("digest-presence-mismatch", "a COMMAND step needs a 64-hex extracted_command_digest")
        if rc is not None:
            add("digest-presence-mismatch", f"a COMMAND step must have reject_code null; got {rc!r}")
    else:  # FORFEIT
        if digest is not None:
            add("digest-presence-mismatch", f"a FORFEIT step must have extracted_command_digest null; got {digest!r}")
        if rc not in REJECT_CODES:
            add("invalid-enum", f"a FORFEIT step's reject_code must be one of {sorted(REJECT_CODES)}; got {rc!r}")
    return problems


def _envelope_binding(step: dict, scenario_dir: Path, where: str) -> tuple[int, object]:
    """Tier-3 request-envelope BINDING (§2.3-2.4), dispatched on prompt_version. Returns (rc, payload):
      rc 2 -> a fail-closed reason string (unknown / registered-but-unapproved version);
      rc 1 -> a single (code, where, msg) problem (the re-render did not match the recorded sha);
      rc 0 -> bound (template re-render matched) or integrity-only (no re-render owed).
    A REGISTERED+APPROVED template version is re-rendered from the committed decision head's fog view and
    bound by sha256 -- catching a self-consistent request tamper (bytes re-hash fine, but are NOT the render
    of the authorized template applied to the authorized fog view). The reserved INTEGRITY_ONLY versions are
    Tier-1 only (re-hash, done by the caller). Any other version is unknown -> fail closed."""
    pv = step["prompt_version"]
    if pv in INTEGRITY_ONLY_PROMPT_VERSIONS:
        return 0, None                                  # offline synthetic envelope: Tier-1 re-hash only
    if pv not in PROMPT_TEMPLATES:
        return 2, f"{where}: prompt_version {pv!r} is neither a registered template nor the reserved " \
                  f"integrity-only sentinel {INTEGRITY_ONLY_PROMPT_VERSIONS} — fail closed"
    if pv not in APPROVED_PROMPT_VERSIONS:              # registered != audited (§2.2 leg 1)
        return 2, f"{where}: prompt_version {pv!r} is registered but NOT on APPROVED_PROMPT_VERSIONS (unaudited)"
    rec_path = scenario_dir / "run" / "turns" / f"{step['turn']:04d}.json"
    if not rec_path.is_file():
        return 1, ("turn-record-missing", where, f"run/turns/{rec_path.name} absent for the envelope binding")
    # The decision head is the single-turn T=0 head: the player decided on the PRE-turn state (start_state)
    # with no events yet. Re-render that slot's fog projection and bind it (the EXISTING projector + template).
    # A malformed/unparseable record (missing start_state, bad entities) means we CANNOT re-render -> fail
    # CLOSED (exit 2) with a clean message, matching the gate's other "cannot reproduce" paths -- never a raw
    # traceback (which would still exit non-zero, but inconsistently with the v1 path's clean finding).
    try:
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        decision_head = {"turn": step["turn"], "resulting_state": rec["start_state"], "event_batch": []}
        view = project_turn_record(step["calling_slot"], decision_head)
        rerendered = hashlib.sha256(canonical_request_bytes(pv, view)).hexdigest()
    except (KeyError, ValueError, TypeError) as exc:   # ValueError covers JSONDecodeError + CanonError
        return 2, f"{where}: cannot re-render the request envelope from the committed record " \
                  f"({type(exc).__name__}: {exc}) — fail closed"
    if rerendered != step["request_envelope_sha256"]:
        return 1, ("request-envelope-binding-mismatch", where,
                   "re-rendered request envelope sha != recorded request_envelope_sha256 (Tier-3 template binding)")
    return 0, None


def _binding_problems(step: dict, scenario_dir: Path, where: str) -> tuple[int, list]:
    """Tier-1 byte integrity + Tier-2 extractor dispatch + H7a/H7b binding for ONE structurally-valid step.
    Returns (rc, problems): rc 2 fail-closed (a version this build cannot reproduce), else (0/1, problems)."""
    problems: list[tuple[str, str, str]] = []

    def add(code: str, msg: str) -> None:
        problems.append((code, where, msg))

    # Tier-2 dispatch: a recorded extractor_version this build does not implement is FAIL-CLOSED (never run
    # HEAD silently against an old record). Today only EXTRACTOR_VERSION is registered.
    if step["extractor_version"] != EXTRACTOR_VERSION:
        return 2, f"{where}: extractor_version {step['extractor_version']!r} is not reproducible by this build " \
                  f"(have {EXTRACTOR_VERSION!r})"

    # Tier-1: the content-addressed response bytes re-hash to the recorded response_sha256.
    llm_dir = scenario_dir / "run" / "llm"
    for f in ("response_sha256", "request_envelope_sha256"):
        artifact = llm_dir / f"{step[f]}.json"
        if not artifact.is_file():
            add("artifact-missing", f"{f} bytes {artifact.name} are not committed under run/llm/")
        elif _sha256(artifact) != step[f]:
            add("response-bytes-tampered" if f == "response_sha256" else "request-envelope-tampered",
                f"sha256(run/llm/{artifact.name}) != recorded {f}")
    if problems:
        return 1, problems

    # re-run the strict extractor on the recorded RESPONSE bytes (Tier-2).
    raw = (llm_dir / f"{step['response_sha256']}.json").read_bytes()
    res = extract_command(raw)
    if step["step_kind"] == "FORFEIT":
        if res.ok:
            add("spurious-forfeit", "a FORFEIT step's bytes actually extract one clean command")
        elif res.reject_code != step["reject_code"]:
            add("forfeit-code-mismatch",
                f"recompute reject_code {res.reject_code!r} != recorded {step['reject_code']!r}")
        erc, epay = _envelope_binding(step, scenario_dir, where)   # Tier-3 (a forfeit still rendered a request)
        if erc == 2:
            return 2, epay
        if epay:
            problems.append(epay)
        return (1 if problems else 0), problems
    # COMMAND
    if not res.ok:
        add("missing-command", f"a COMMAND step's bytes do not extract a command ({res.reject_code})")
        return 1, problems
    recompute = canonical_digest(project_semantic(res.command))["value"]
    if recompute != step["extracted_command_digest"]:
        add("recorded-digest-mismatch",
            "recorded extracted_command_digest != re-extract from bytes (the gate never trusts the stored digest)")

    # the committed turn record + the slot's command (H7a/H7b).
    rec_path = scenario_dir / "run" / "turns" / f"{step['turn']:04d}.json"
    if not rec_path.is_file():
        add("turn-record-missing", f"run/turns/{rec_path.name} is not committed for turn {step['turn']}")
        return 1, problems
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    # actor_id is bound BY SELECTION: a command mis-bound to the wrong actor yields 0 matches for this
    # slot (slot-command-count), so no separate actor-slot check is needed (it would be dead code).
    batch = [c for c in rec.get("command_batch", []) if c.get("actor_id") == step["calling_slot"]]
    if len(batch) != 1:
        add("slot-command-count",
            f"expected exactly 1 committed command with actor_id == calling_slot {step['calling_slot']!r}, "
            f"found {len(batch)}")
        return 1, problems
    cmd = batch[0]
    # H7a semantic binding (digest over {action_type, params} only).
    if canonical_digest(project_semantic(cmd))["value"] != recompute:
        add("semantic-digest-mismatch",
            "committed command's {action_type,params} != what the recorded bytes extract to")
    # H7b identity binding: command_id + turn must equal the harness-derived values (actor_id via selection).
    expected_id = f"{step['run_id']}:{step['turn']}:{step['calling_slot']}"
    if cmd.get("command_id") != expected_id:
        add("command-id-mismatch", f"committed command_id {cmd.get('command_id')!r} != harness-bound {expected_id!r}")
    as_of = (rec.get("start_state") or {}).get("state", {}).get("as_of_turn")
    if not (cmd.get("turn") == step["turn"] == rec.get("turn") == as_of):
        add("turn-mismatch",
            f"command.turn/{cmd.get('turn')} step.turn/{step['turn']} record.turn/{rec.get('turn')} "
            f"start.as_of_turn/{as_of} must all be equal")
    erc, epay = _envelope_binding(step, scenario_dir, where)   # Tier-3 request-envelope binding (§2.3-2.4)
    if erc == 2:
        return 2, epay
    if epay:
        problems.append(epay)
    return (1 if problems else 0), problems


def _judge_scenario(scenario_dir: Path) -> tuple[int, object]:
    """Validate every llm_step in scenario_dir/run_ledger.yaml. Returns (rc, payload): rc 0/1/2; payload is
    an (n_steps) count (0), a problems list (1), or a fail-closed reason (2)."""
    ledger_path = scenario_dir / "run_ledger.yaml"
    ldoc, lerr = load_registry(ledger_path)
    if lerr is not None or not isinstance(ldoc, dict):
        return 2, lerr or f"{ledger_path} is not a usable run-ledger"
    steps = ldoc.get("llm_steps")
    if steps is None:
        return 0, 0                       # no agent steps in this scenario (vacuous)
    if not isinstance(steps, list) or not steps:
        return 1, [("malformed-llm_steps", _display(ledger_path), f"llm_steps must be a non-empty list; got {steps!r}")]
    all_problems: list[tuple[str, str, str]] = []
    for i, step in enumerate(steps):
        where = f"{_display(ledger_path)}#llm_steps[{i}]"
        sproblems = _structural_problems(step, where)
        if sproblems:
            all_problems.extend(sproblems)
            continue                       # structure first (single-fault); skip binding on a broken step
        rc, bproblems = _binding_problems(step, scenario_dir, where)
        if rc == 2:
            return 2, bproblems            # a version this build can't reproduce taints the gate
        all_problems.extend(bproblems)
    # CARDINALITY: at most ONE step per (turn, calling_slot). Rejects a PADDED log (two COMMAND steps
    # binding the same command) or a CONTRADICTORY FORFEIT+COMMAND pair for one slot -- a provenance log
    # must be a function, not a multiset. (A FORFEIT for a slot that DID commit a command is separately
    # caught by COVERAGE: the command has no backing COMMAND step -> uncovered-command.)
    if not all_problems:
        seen: set = set()
        for i, step in enumerate(steps):
            key = (step["turn"], step["calling_slot"])
            if key in seen:
                all_problems.append(("duplicate-step", f"{_display(ledger_path)}#llm_steps[{i}]",
                    f"a second llm_step for (turn {step['turn']}, slot {step['calling_slot']!r}); "
                    "at most one step per (turn, slot)"))
            seen.add(key)
    # COVERAGE (the converse binding): in a scenario WITH provenance, every committed agent command must
    # have a backing COMMAND step -- else a FABRICATED command with no step would ride through unaudited
    # (the step->command binding alone does not catch a command->no-step gap). Only runs once provenance is
    # populated, so scripted-command scenarios (llm_steps: null) are never false-positived.
    if not all_problems:
        covered = {(s["turn"], s["calling_slot"]) for s in steps if s.get("step_kind") == "COMMAND"}
        for rec_path in sorted((scenario_dir / "run" / "turns").glob("*.json")):
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
            for cmd in rec.get("command_batch", []):
                if (rec.get("turn"), cmd.get("actor_id")) not in covered:
                    all_problems.append(("uncovered-command", _display(rec_path),
                        f"committed command for slot {cmd.get('actor_id')!r} at turn {rec.get('turn')} has "
                        f"no backing llm_step (a scenario with provenance must have COMPLETE provenance)"))
    if all_problems:
        return 1, all_problems
    return 0, len(steps)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="validate_agent_provenance.py",
        description="Validate an offline agent run's non-causal llm_steps provenance (the H7 binding).",
    )
    parser.add_argument("--scenario-dir", default=None,
                        help="validate one scenario (default: sweep examples/**/run_ledger.yaml)")
    args = parser.parse_args(argv)

    if args.scenario_dir:
        rc, payload = _judge_scenario(Path(args.scenario_dir).resolve())
        if rc == 2:
            return _fail_closed(payload)
        if rc == 1:
            return _report(payload)
        print(f"agent-provenance OK ({payload} step(s) bound)")
        return 0

    ledgers = sorted((REPO_ROOT / "examples").glob("**/run_ledger.yaml"))
    all_problems: list[tuple[str, str, str]] = []
    total_steps = 0
    for ledger in ledgers:
        rc, payload = _judge_scenario(ledger.parent)
        if rc == 2:
            return _fail_closed(payload)
        if rc == 1:
            all_problems.extend(payload)
        else:
            total_steps += payload
    if all_problems:
        return _report(all_problems)
    print(f"agent-provenance OK ({len(ledgers)} ledger(s) swept, {total_steps} step(s) bound)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
