"""Bounded threshold feedback and live re-ranking (Stage 07, plan sections 5.7 and 5.9)."""

import copy
import math
import random

import pytest
from ringsentinel.review.feedback import (
    HARD_MAX_CONFIRM_WEIGHT,
    HARD_MAX_OFFSET,
    HARD_MAX_STEP,
    FeedbackConfig,
    adjusted_score,
    annotate,
    count_decisions,
    effective_threshold,
    export_order,
    logit,
    sigmoid,
    threshold_offset,
)

COST = {"review_cost_inr": 250.0, "fp_cost_inr": 500.0, "loss_capture_rate": 1.0}
CFG = FeedbackConfig()  # step 0.1, max 1.5, confirm weight 1


def item(n, score, amount=100000.0, members=4):
    return {
        "ring_id": f"R-{n:012x}", "rank": n, "score": score, "expected_value_inr": 0.0,
        "n_members": members, "n_transfers": 5, "amount_inr": amount, "oversized": False,
        "top_features": [],
    }  # fmt: skip


# --------------------------------------------------------------- the offset and its bounds
def test_hand_cases():
    assert threshold_offset(0, 0, CFG) == 0.0
    assert threshold_offset(0, 5, CFG) == pytest.approx(0.5)
    assert threshold_offset(2, 5, CFG) == pytest.approx(0.3)
    assert threshold_offset(3, 5, CFG) == pytest.approx(0.2)
    assert threshold_offset(6, 5, CFG) == 0.0  # confirmations cannot push below zero
    assert threshold_offset(0, 15, CFG) == pytest.approx(1.5)
    assert threshold_offset(0, 16, CFG) == pytest.approx(1.5)  # clamped at the bound


def test_repeated_dismissals_cannot_leave_the_bounds():
    """The plan's test: however many dismissals arrive, the threshold stays inside its bounds."""
    base = 0.0095
    ceiling = sigmoid(logit(base) + CFG.max_offset)
    previous = -1.0
    for n in [*range(0, 200), 1_000, 10_000, 1_000_000, 10**12]:
        off = threshold_offset(0, n, CFG)
        assert 0.0 <= off <= CFG.max_offset
        eff = effective_threshold(base, off)
        assert base <= eff <= ceiling + 1e-12
        assert off >= previous  # more dismissals never lower it
        previous = off
    assert effective_threshold(base, threshold_offset(0, 10**12, CFG)) == pytest.approx(ceiling)


def test_random_decision_sequences_stay_in_bounds_and_are_order_independent():
    rng = random.Random(7)
    for _ in range(300):
        c, d = rng.randrange(0, 400), rng.randrange(0, 400)
        cfg = FeedbackConfig(
            step=rng.uniform(0, HARD_MAX_STEP), max_offset=rng.uniform(0, HARD_MAX_OFFSET),
            confirm_weight=rng.uniform(0, HARD_MAX_CONFIRM_WEIGHT),
        )  # fmt: skip
        off = threshold_offset(c, d, cfg)
        assert 0.0 <= off <= cfg.max_offset
        assert threshold_offset(c, d + 1, cfg) >= off  # monotone in dismissals
        assert threshold_offset(c + 1, d, cfg) <= off  # and in confirmations


def test_zero_max_offset_means_feedback_is_switched_off():
    off_cfg = FeedbackConfig(max_offset=0.0)
    assert threshold_offset(0, 10_000, off_cfg) == 0.0
    rows, state = annotate(
        [item(1, 0.5)], {item(1, 0.5)["ring_id"]: "dismissed"}, 0.01, COST, off_cfg
    )
    assert state["offset_logit"] == 0.0 and state["at_bound"] is False
    assert rows[0]["live"]["adjusted_score"] == 0.5


def test_negative_counts_are_refused():
    with pytest.raises(ValueError):
        threshold_offset(-1, 0, CFG)
    with pytest.raises(ValueError):
        threshold_offset(0, -1, CFG)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"step": -0.1}, {"max_offset": -1}, {"confirm_weight": -1},
        {"step": HARD_MAX_STEP + 0.01}, {"max_offset": HARD_MAX_OFFSET + 0.01},
        {"confirm_weight": HARD_MAX_CONFIRM_WEIGHT + 0.01}, {"step": float("nan")},
        {"max_offset": float("inf")}, {"step": True}, {"step": "0.1"},
    ],
)  # fmt: skip
def test_the_configuration_cannot_open_the_bounds(kwargs):
    with pytest.raises(ValueError):
        FeedbackConfig(**kwargs)


def test_the_ceilings_themselves_are_allowed():
    FeedbackConfig(step=HARD_MAX_STEP, max_offset=HARD_MAX_OFFSET,
                   confirm_weight=HARD_MAX_CONFIRM_WEIGHT)  # fmt: skip


# --------------------------------------------------------------- score transforms
def test_threshold_never_goes_below_the_validated_value():
    for base in (1e-6, 0.0095, 0.3, 0.99):
        for off in (0.0, 0.2, 1.5, 3.0):
            assert effective_threshold(base, off) >= base - 1e-15
    assert effective_threshold(None, 1.0) is None


def test_adjusted_score_is_identity_at_zero_and_order_preserving():
    scores = [0.011, 0.05, 0.2, 0.5, 0.9, 0.977]
    assert [adjusted_score(s, 0.0) for s in scores] == scores
    for off in (0.1, 0.7, 1.5):
        adj = [adjusted_score(s, off) for s in scores]
        assert adj == sorted(adj) and all(0.0 < a < 1.0 for a in adj)
        assert all(a < s for a, s in zip(adj, scores, strict=True))


def test_effective_threshold_and_adjusted_score_agree():
    base, off = 0.0095, 0.8
    eff = effective_threshold(base, off)
    for s in (0.01, 0.0143, 0.02, 0.3):
        assert (s >= eff) == (adjusted_score(s, off) >= base - 1e-12)


def test_extreme_scores_do_not_blow_up():
    for s in (0.0, 1.0, 1e-300, 1 - 1e-16):
        assert math.isfinite(adjusted_score(s, 1.5)) and 0.0 <= adjusted_score(s, 1.5) <= 1.0


# --------------------------------------------------------------- annotate / live queue
def test_without_decisions_live_order_follows_adjusted_value_and_changes_nothing_stored():
    items = [item(1, 0.9, 100000), item(2, 0.5, 300000), item(3, 0.2, 50000)]
    before = copy.deepcopy(items)
    rows, state = annotate(items, {}, 0.01, COST, CFG)
    assert items == before  # the inputs are never modified
    assert state["offset_logit"] == 0.0 and state["effective_threshold"] == 0.01
    assert state["n_pending"] == 3 and state["n_active"] == 3 and state["validated"] is False
    for r in rows:
        stored = next(i for i in items if i["ring_id"] == r["ring_id"])
        for key in ("score", "rank", "expected_value_inr", "amount_inr", "n_members"):
            assert r[key] == stored[key]  # stored fields untouched
        assert r["live"]["adjusted_score"] == stored["score"]
    values = [r["live"]["adjusted_expected_value_inr"] for r in rows]
    assert values == sorted(values, reverse=True)
    assert [r["live"]["live_rank"] for r in rows] == [1, 2, 3]


def test_dismissals_raise_the_threshold_and_deprioritise_the_marginal_rings():
    items = [
        item(i, s, amount=1_000_000.0)
        for i, s in enumerate([0.9, 0.5, 0.05, 0.012, 0.011], start=1)
    ]
    statuses = {items[0]["ring_id"]: "dismissed"}
    cfg = FeedbackConfig(step=1.0, max_offset=3.0)
    rows, state = annotate(items, statuses, 0.01, COST, cfg)
    assert state["offset_logit"] == 1.0 and state["n_dismissed"] == 1
    assert state["effective_threshold"] == pytest.approx(sigmoid(logit(0.01) + 1.0))
    below = [r for r in rows if r["status"] == "pending" and not r["live"]["above_threshold"]]
    assert {r["score"] for r in below} == {0.012, 0.011}  # now under the shifted threshold
    assert all(r["live"]["live_rank"] is None for r in below)
    assert rows[-1]["status"] == "dismissed"  # decided rings sort last
    active = [r["live"]["live_rank"] for r in rows if r["live"]["live_rank"]]
    assert active == list(range(1, len(active) + 1))
    assert state["n_active"] == len(active) == 2 and state["n_deprioritised"] == 2


def test_confirmations_offset_dismissals_but_never_lower_the_validated_threshold():
    items = [item(i, 0.3) for i in range(1, 6)]
    ids = [i["ring_id"] for i in items]
    statuses = {ids[0]: "dismissed", ids[1]: "dismissed", ids[2]: "confirmed"}
    _, state = annotate(items, statuses, 0.01, COST, CFG)
    assert state["offset_logit"] == pytest.approx(0.1)
    more = {**statuses, ids[3]: "confirmed", ids[4]: "confirmed"}
    _, state = annotate(items, more, 0.01, COST, CFG)
    assert state["offset_logit"] == 0.0 and state["effective_threshold"] == 0.01


def test_held_counts_for_nothing_and_stays_open():
    items = [item(1, 0.5), item(2, 0.4)]
    rows, state = annotate(items, {items[0]["ring_id"]: "held"}, 0.01, COST, CFG)
    assert state["offset_logit"] == 0.0 and state["n_held"] == 1
    held = next(r for r in rows if r["status"] == "held")
    assert held["live"]["live_rank"] is not None  # still needs a decision


def test_a_ring_that_costs_more_than_it_is_worth_is_deprioritised_not_hidden():
    items = [item(1, 0.5, amount=100.0, members=10), item(2, 0.5, amount=500000.0)]
    rows, _ = annotate(items, {}, 0.01, COST, CFG)
    losing = next(r for r in rows if r["ring_id"] == items[0]["ring_id"])
    assert losing["live"]["adjusted_expected_value_inr"] < 0 and losing["live"]["live_rank"] is None
    assert len(rows) == 2


def test_statuses_for_rings_outside_the_bundle_are_ignored():
    items = [item(1, 0.5)]
    stray = {"R-ffffffffffff": "dismissed", items[0]["ring_id"]: "pending"}
    assert count_decisions(stray, [items[0]["ring_id"]])["dismissed"] == 0
    _, state = annotate(items, stray, 0.01, COST, CFG)
    assert state["offset_logit"] == 0.0 and state["n_in_bundle"] == 1


def test_thousands_of_dismissals_through_annotate_stay_bounded():
    items = [item(i, 0.2 + (i % 7) / 100) for i in range(1, 2001)]
    statuses = {i["ring_id"]: "dismissed" for i in items}
    _, state = annotate(items, statuses, 0.0095, COST, CFG)
    assert state["offset_logit"] == CFG.max_offset and state["at_bound"] is True
    assert state["effective_threshold"] == pytest.approx(sigmoid(logit(0.0095) + 1.5))


def test_no_threshold_means_nothing_is_above_it():
    rows, state = annotate([item(1, 0.5)], {}, None, COST, CFG)
    assert state["effective_threshold"] is None and state["n_active"] == 0
    assert rows[0]["live"]["above_threshold"] is False


def test_live_order_is_deterministic_and_export_order_restores_rank():
    items = [item(i, 0.3 + i / 100, amount=1000.0 * (i % 3 + 1)) for i in range(1, 30)]
    a, _ = annotate(items, {}, 0.01, COST, CFG)
    b, _ = annotate(list(reversed(items)), {}, 0.01, COST, CFG)
    assert [r["ring_id"] for r in a] == [r["ring_id"] for r in b]
    assert [r["rank"] for r in export_order(a)] == sorted(r["rank"] for r in a)
