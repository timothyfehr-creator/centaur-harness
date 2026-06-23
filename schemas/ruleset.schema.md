# Ruleset schema (v1) — a resolver's parameters, with provenance

Contract for a per-scenario `rules.yaml` (e.g. `examples/<name>/rules.yaml`). Enforced by
[`scripts/validate_ruleset.py`](../scripts/validate_ruleset.py) (a `release`-tier gate). A ruleset is the
resolver's **parameters** carried as a `{value, source}` provenance tree; a salvo loader (e.g.
`scripts/salvo_het_run.py`) **flattens** it into the int-only ruleset the engine hashes into the
`transition_input_hash` preimage — the `source` provenance stays in the YAML, never in the digest.

## Document shape

```yaml
schema_version: "1.0"
ruleset_id: ru_ua_salvo_heterogeneous
ruleset_version: "1"
params:                                  # a tree of {value, source} LEAVES, nested freely
  p_intercept_pct:                       # a grouping (no `value` key) -> recurse
    drone:  {value: 80, source: "ASSUMED — UNCALIBRATED (E2c dossier: not separably calibratable)"}
    cruise: {value: 65, source: "ASSUMED — UNCALIBRATED placeholder"}
  lethality_floor_pct:                   # per-class WEAKEST-LINK culmination floors (a grouping)
    drone:     {value: 50, source: "ASSUMED, LOCKED (doctrinal)"}
    cruise:    {value: 40, source: "ASSUMED — contract extension"}
    ballistic: {value: 25, source: "ASSUMED — contract extension"}
  threat_order: {value: [ballistic, cruise, drone], source: "ASSUMED — scarce-interceptor priority"}
  ballistic_leak_floor_pct: {value: 60, source: "ASSUMED — dossier-illustrative (exogenous); not a calibrated cell"}
```

## Fields

| Field | Required | Rule |
|---|---|---|
| `schema_version` | yes | non-empty string |
| `ruleset_id` | yes | non-empty string (matches the resolver's `RESOLVER_ID` family) |
| `ruleset_version` | yes | non-empty string |
| `params` | yes | a non-empty mapping; a tree of `{value, source}` leaves (groupings nest freely) |

### Param leaves (walked recursively)

A node with a `value` key is a **leaf**; any other mapping is a **grouping** to recurse into. Every leaf:

| Field | Required | Rule |
|---|---|---|
| `value` | yes | `int` / `str` / `bool`, or a list of those. **NO float** — canon-v1 is float-free; a float would crash the engine digest (`float-not-allowed`). |
| `source` | yes | a **non-empty** provenance string (`missing-source` otherwise) — the epistemic-discipline rule: **no number without a citation or an `ASSUMED` tag**. |

### Source-tag taxonomy (convention)

`ASSUMED` (placeholder, needs calibration) · `SOURCED-RANGE (exogenous)` (a bounded range propagated as a
sensitivity band) · `EXPLORATORY` (a what-if anchor) · `STRUCTURALLY-UNIDENTIFIABLE` (a cell no data can
constrain — e.g. the interceptor-axis per-pairing rates — excluded from the calibration gate, WP-E2c).
There is **no `CALIBRATION TARGET` tag**: the WP-E2c data dossier found the kinetic drone/cruise intercept
rates are NOT separably calibratable for the available window (mono-source, composite bucket, no
method-independent corroborator), so they stay `ASSUMED`/UNCALIBRATED and E2c ships a calibration-FEASIBILITY
record rather than a calibration claim.

## What this gate does NOT check (by design)

Resolver-**specific BOUNDS** (`0 <= p_intercept_pct <= 100`, `interceptors_per_intercept >= 1`,
`ballistic_floor <= high`, allocation ids present in state, ...) are enforced in the resolver's
`validate_all` — an out-of-range ruleset there is a **REJECTED transition** (no record, no crash), not a
gate finding. This gate is the at-rest **structure + provenance + float-free** check, resolver-agnostic.

## Error codes

`missing-schema-version`, `missing-field` (absent `ruleset_id`/`ruleset_version`/`params`, or an empty
grouping), `wrong-type` (a non-mapping param node, or a non-canon-scalar value), `float-not-allowed`,
`missing-source`, `yaml-parse-error`. Fail-closed (exit 2): an unreadable file, or a default/dir scan that
finds zero `rules.yaml`.
