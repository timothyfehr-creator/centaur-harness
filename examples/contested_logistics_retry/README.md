# Contested logistics — live model-RETRY demo (both roads blockable, `CAPTURE_ARTIFACT`)

**This is a `CAPTURE_ARTIFACT`, not a forecast.** One live, non-deterministic multi-turn game in which Opus
4.8 played BOTH sides with **live model-RETRY** (WP-A2) enabled. When a player's order is rejected — malformed,
or engine-illegal such as dispatching more than its remaining supply — the engine hands it back with the
**public** reject code and the player is re-asked, up to a bounded budget, before forfeiting the turn. It
demonstrates the retry lane mechanically works; it asserts nothing about the real world.

Read these four disclosures first:

1. **`CAPTURE_ARTIFACT`:** A single non-deterministic game demonstrating the live lane mechanically works;
   not a model, not a sample, not analysis.
2. **Memoryless:** Each player is a memoryless one-shot reasoner ACROSS turns (called fresh on the
   current-turn fog projection). WITHIN a turn a retry additionally sees the public reject code of its own
   just-rejected order — a rules correction, not strategy. Weaker than a remembering adversary; must not be
   presented as a continuous strategist.
3. **Authenticity residual:** capture_mode LIVE is an attestation by the runner, not a proof. A fabricated
   capture is byte-indistinguishable to a third party and would bind green — the gates prove internal
   CONSISTENCY, not byte AUTHENTICITY.
4. **Sample size:** n equals 1. This is a single game, not a sample; nothing here is a frequency, a
   probability, or evidence about the real world, and it must NEVER be aggregated with other games into a
   distribution.

## How retry is recorded (honestly)

Only the **DECISIVE** order (the final accepted command, or — if the budget is exhausted — the final forfeit)
binds the turn's one provenance step. The rejected **prior attempts** are recorded in a non-binding
`prior_attempts` list, each with its own redacted, content-addressed bytes; `validate_agent_provenance.py`
**re-extracts each one and confirms it genuinely rejects** (with the recorded reject code), and checks the
correction chain — so a retry can't be fabricated and a legal move can't be hidden as a discarded "prior".
The correction handed to the model names **only the public reject code**, never a hidden threshold.

## What is committed

The turn-record chain (`run/turns/`), the **redacted** per-turn (and per-retry-attempt) response bytes + the
canonical request envelopes (`run/llm/`, content-addressed), and a `capture_mode: LIVE` provenance entry per
(turn, slot) in `run_ledger.yaml`. The full wire bytes + the spend ledger stay run-local + git-ignored; the
api-key is never written anywhere. The whole game REPLAYS deterministically with the model never re-called.
