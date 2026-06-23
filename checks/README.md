# checks/

Configuration consumed by the safety gates (not code).

- **`safety_patterns.yaml`** — the actionable-harm content patterns that
  [`scripts/safety_check.py`](../scripts/safety_check.py) enforces. Keeping the patterns
  here (rather than inline in the gate) makes the policy reviewable on its own; see
  [docs/COMMAND_SAFETY.md](../docs/COMMAND_SAFETY.md) and
  [docs/SAFETY_AND_SCOPE.md](../docs/SAFETY_AND_SCOPE.md).
