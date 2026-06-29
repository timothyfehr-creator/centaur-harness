# Contested logistics — multi-turn two-player LIVE game (`CAPTURE_ARTIFACT`)

**This is a `CAPTURE_ARTIFACT`, not a forecast.** One live, non-deterministic multi-turn game in which Opus
4.8 played BOTH sides over several turns, refereed by the deterministic engine. It demonstrates the
multi-turn / two-player live game lane mechanically works; it asserts nothing about the real world.

Read these four disclosures first:

1. **`CAPTURE_ARTIFACT`:** A single non-deterministic game demonstrating the live lane mechanically works;
   not a model, not a sample, not analysis.
2. **Memoryless:** Each player is a memoryless one-shot reasoner; on every turn it is called fresh and sees
   only the current-turn fog projection — no prior turn, no message history, no memory of its own past moves.
   This is weaker than a remembering adversary and must not be presented as a continuous strategist.
3. **Authenticity residual:** capture_mode LIVE is an attestation by the runner, not a proof. A fabricated
   capture is byte-indistinguishable to a third party and would bind green — the gates prove internal
   CONSISTENCY, not byte AUTHENTICITY.
4. **Sample size:** n equals 1. This is a single game, not a sample; nothing here is a frequency, a
   probability, or evidence about the real world, and it must NEVER be aggregated with other games into a
   distribution.

## What is committed

The turn-record chain (`run/turns/`), the **redacted** per-turn response bytes + the canonical request
envelopes (`run/llm/`, content-addressed), and a `capture_mode: LIVE` provenance entry per (turn, slot) in
`run_ledger.yaml`. The model's free-text prose is stripped before hashing and never committed; the full wire
bytes + the spend ledger stay run-local + git-ignored; the api-key is never written anywhere. The whole game
REPLAYS deterministically (chain check + per-turn provenance + Tier-3 + fog) with the model never re-called.
