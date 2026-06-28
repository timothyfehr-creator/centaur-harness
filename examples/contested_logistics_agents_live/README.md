# Contested logistics — LIVE capture (`CAPTURE_ARTIFACT`)

**This is a `CAPTURE_ARTIFACT`, not a forecast.** It records one live, non-deterministic capture in which
Opus 4.8 played BLUE and RED of a single contested-logistics turn, refereed by the deterministic engine. It
demonstrates the live lane mechanically works; it asserts nothing about the real world.

Read these four disclosures before anything else:

1. **`CAPTURE_ARTIFACT`:** A captured live game is a single non-deterministic capture demonstrating the live
   lane mechanically works; not a model, not a sample, not analysis.
2. **Memoryless:** Each player is a memoryless one-shot reasoner; it sees only the current-turn fog
   projection and no prior turn, message, or its own past reasoning. This is weaker than a remembering
   adversary and must not be presented as a continuous strategist.
3. **Authenticity residual:** capture_mode LIVE is an attestation by the runner, not a proof. A fabricated
   capture is byte-indistinguishable to a third party and would bind green — the gates prove internal
   CONSISTENCY, not byte AUTHENTICITY.
4. **Sample size:** n equals 1. This is a single capture, not a sample; nothing here is a frequency, a
   probability, or evidence about the real world.

## What is committed (and what is not)

- Committed: the turn record (`run/turns/`), the **redacted** response bytes + the canonical request envelope
  (`run/llm/`, content-addressed), and a `capture_mode: LIVE` provenance entry per slot in `run_ledger.yaml`.
  The model's free-text strategic prose is **stripped before hashing** and never committed.
- Not committed (run-local, git-ignored): the full raw wire bytes (which carry the prose) and the advisory
  spend ledger. The api-key is never written anywhere.

## How it was produced / how it replays

Produced once by `scripts/agent_live_capture.py` (the `@live` lane — out of the green gate). It REPLAYS
deterministically: `validate_agent_provenance` (the H7 binding + the LIVE checks + the Tier-3 request-envelope
binding), `validate_agent_fog` (differential no-leak), `validate_turn_replay` (byte-identical), and
`validate_no_prose` all pass on the committed bytes **with the model never re-called**.
