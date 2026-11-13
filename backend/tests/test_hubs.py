import json

import numpy as np
import pytest
from ringsentinel.config import DEFAULT_HUB_CAP, Settings
from ringsentinel.graph.hubs import choose_hub_cap, effective_hub_cap, hub_mask, idf_weight


def test_idf_weight_hand_values_and_monotone():
    assert idf_weight(1) == pytest.approx(1.0)
    assert idf_weight(3) == pytest.approx(0.5)
    assert idf_weight(7) == pytest.approx(1 / 3)
    w = idf_weight(np.arange(1, 200))
    assert (np.diff(w) < 0).all()


def test_hub_mask_cap_is_inclusive():
    degree = np.array([1, 9, 10, 11, 500])
    assert hub_mask(degree, 10).tolist() == [False, False, False, True, True]


def test_choose_hub_cap_picks_smallest_cap_meeting_retention():
    degree = np.zeros(10, dtype=int)
    degree[:6] = [3, 5, 8, 12, 19, 40]
    protected = np.arange(6)
    out = choose_hub_cap(degree, protected, grid=(10, 20, 50), min_retention=0.99)
    assert out["chosen_cap"] == 50 and not out["fallback_to_largest"]
    relaxed = choose_hub_cap(degree, protected, grid=(10, 20, 50), min_retention=0.8)
    assert relaxed["chosen_cap"] == 20
    assert [r["ring_account_retention"] for r in out["table"]] == pytest.approx([3 / 6, 5 / 6, 1])


def test_choose_hub_cap_falls_back_and_says_so():
    degree = np.array([99, 3])
    out = choose_hub_cap(degree, np.array([0, 1]), grid=(10, 20))
    assert out["chosen_cap"] == 20 and out["fallback_to_largest"] is True


def test_effective_hub_cap_precedence(tmp_path):
    settings = Settings(data_dir=tmp_path)
    assert effective_hub_cap(settings) == DEFAULT_HUB_CAP
    settings.hub_cap_tuning_path.parent.mkdir(parents=True)
    settings.hub_cap_tuning_path.write_text(json.dumps({"chosen_cap": 20}), encoding="utf-8")
    assert effective_hub_cap(settings) == 20
    assert effective_hub_cap(Settings(data_dir=tmp_path, hub_cap=7)) == 7
