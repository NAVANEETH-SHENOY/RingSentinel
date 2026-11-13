import inspect

import numpy as np
import pandas as pd
from ringsentinel.noise import (
    ATTRIBUTE_COLUMNS,
    attribute_degree,
    build_noise,
    independence_report,
)

ACCOUNTS = [f"8{i:07X}" for i in range(20000)]


def test_deterministic_and_order_independent():
    first = build_noise(ACCOUNTS, 42)
    again = build_noise(list(reversed(ACCOUNTS)), 42)
    pd.testing.assert_frame_equal(first, again)
    other = build_noise(ACCOUNTS, 43)
    assert not first["derived_ip_id"].equals(other["derived_ip_id"])


def test_one_row_per_account_and_derived_names():
    noise = build_noise(ACCOUNTS + ACCOUNTS[:10], 42)
    assert len(noise) == len(ACCOUNTS) and noise["account"].is_unique
    assert all(c.startswith("derived_") for c in ATTRIBUTE_COLUMNS)
    assert list(noise.columns) == ["account", *ATTRIBUTE_COLUMNS]


def test_sharing_structure_has_hubs_households_and_small_groups():
    noise = build_noise(ACCOUNTS, 42)
    ip = attribute_degree(noise, "derived_ip_id")
    device = attribute_degree(noise, "derived_device_id")
    vpa = attribute_degree(noise, "derived_vpa_handle_id")
    assert ip.max() > 50  # a carrier-style hub IP exists
    assert device.max() <= 4  # shared devices are small family groups
    assert vpa.max() > 1000 and noise["derived_vpa_handle_id"].nunique() <= 12
    assert (device == 1).mean() > 0.8  # most devices are unique


def test_build_noise_has_no_access_to_labels():
    # Structural guarantee: the only inputs are the account list and the seed.
    assert list(inspect.signature(build_noise).parameters) == ["accounts", "seed"]


def test_independent_subset_shows_no_difference():
    noise = build_noise(ACCOUNTS, 42)
    rng = np.random.default_rng(99)
    ring_like = set(rng.choice(noise["account"].to_numpy(), size=600, replace=False))
    report = independence_report(noise, ring_like)
    assert report["n_flagged_accounts"] == 600
    assert report["min_p_value"] > 0.001


def test_the_independence_check_has_power_to_catch_dependence():
    noise = build_noise(ACCOUNTS, 42)
    on_hub_ip = noise[attribute_degree(noise, "derived_ip_id") > 50]["account"]
    report = independence_report(noise, set(on_hub_ip))
    assert report["attributes"]["derived_ip_id"]["p_value"] < 1e-6
