"""Tests for core/spend_guard.py (WP-A1b §4.1 — the proactive token spend guard)."""
from __future__ import annotations

import spend_guard as sg


def test_affordable_is_proactive_not_after_the_fact() -> None:
    # the FIRST call must be refusable: a single pathological call whose ceiling already exceeds the cap.
    assert sg.affordable(spent_tokens=0, this_call_ceiling=5_000, token_cap=20_000)
    assert not sg.affordable(spent_tokens=0, this_call_ceiling=500_000, token_cap=20_000)  # huge input, 1st call
    # boundary: exactly-at-cap is allowed; one over is refused.
    assert sg.affordable(10_000, 10_000, 20_000)
    assert not sg.affordable(10_000, 10_001, 20_000)


def test_call_ceiling_counts_input_plus_output_budget() -> None:
    assert sg.call_ceiling_tokens(input_tokens=320, max_tokens=1024) == 1344


def test_micro_usd_is_exact_integer() -> None:
    # 1024 output tokens at $25/MTok = 25_600 micro-$ = $0.0256; + 320 input at $5/MTok = 1_600 micro-$.
    assert sg.micro_usd(input_tokens=320, output_tokens=1024) == 320 * 5 + 1024 * 25 == 27_200
    assert sg.format_usd(27_200) == "$0.027200"


def test_two_toy_calls_fit_the_default_cap() -> None:
    # a contested turn = 2 calls of (~320 input + 1024 output); both must fit the default cap.
    ceiling = sg.call_ceiling_tokens(320, 1024)
    spent = 0
    for _ in range(2):
        assert sg.affordable(spent, ceiling, sg.DEFAULT_TOKEN_CAP)
        spent += ceiling
    assert spent < sg.DEFAULT_TOKEN_CAP
