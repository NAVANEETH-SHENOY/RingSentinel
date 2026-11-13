"""Derived, label-blind noise layer (data stage D3).

The IBM data has no device, IP or VPA information, so this module INVENTS it, purely to test
hub robustness. It is synthetic, marked derived everywhere (column names start with
`derived_`), and never used as a detection signal.

Label-blind by construction: build_noise() receives only the list of account strings and a
seed. It has no access to labels, ring ids, amounts or times. independence_report() checks the
same thing statistically after the fact.

Three attribute kinds, all assigned per account:
  * derived_ip_id: a few hub IPs (carrier-grade NAT, cafe wifi) shared by very many accounts,
    household IPs shared by 2 to 4 accounts, and unique IPs.
  * derived_device_id: mostly unique devices, some shared by 2 to 4 accounts (family phone).
  * derived_vpa_handle_id: one of 12 provider handles, a handful of ultra-hubs by design.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

ATTRIBUTE_COLUMNS = ("derived_ip_id", "derived_device_id", "derived_vpa_handle_id")

N_HUB_IPS = 40
HUB_IP_SHARE = 0.03  # share of accounts placed on a hub IP
HOUSEHOLD_IP_SHARE = 0.40  # share on a household IP (2 to 4 accounts)
SHARED_DEVICE_SHARE = 0.12
N_VPA_HANDLES = 12

# id ranges keep the three kinds apart inside one attribute column
_HUB_BASE, _GROUP_BASE, _UNIQUE_BASE = 0, 1_000, 100_000_000


def _group_ids(n: int, rng: np.random.Generator) -> np.ndarray:
    """Randomly partition n items into groups of 2 to 4; returns the group id of each item."""
    if n == 0:
        return np.zeros(0, dtype="int64")
    sizes = rng.integers(2, 5, size=n // 2 + 2)
    ends = np.cumsum(sizes)
    position_group = np.searchsorted(ends, np.arange(n), side="right")
    out = np.empty(n, dtype="int64")
    out[rng.permutation(n)] = position_group
    return out


def _zipf_weights(k: int, exponent: float = 1.2) -> np.ndarray:
    w = 1.0 / np.arange(1, k + 1) ** exponent
    return w / w.sum()


def build_noise(accounts: list[str] | np.ndarray | pd.Index, seed: int) -> pd.DataFrame:
    """Return one row per account with the three derived attribute columns."""
    ordered = np.array(sorted(set(map(str, accounts))), dtype=object)
    n = len(ordered)
    rng = np.random.default_rng(seed)

    # --- IP ---
    ip = _UNIQUE_BASE + np.arange(n, dtype="int64")
    draw = rng.random(n)
    on_hub = draw < HUB_IP_SHARE
    on_household = (draw >= HUB_IP_SHARE) & (draw < HUB_IP_SHARE + HOUSEHOLD_IP_SHARE)
    ip[on_hub] = _HUB_BASE + rng.choice(
        N_HUB_IPS, size=int(on_hub.sum()), p=_zipf_weights(N_HUB_IPS)
    )
    ip[on_household] = _GROUP_BASE + _group_ids(int(on_household.sum()), rng)

    # --- device ---
    device = _UNIQUE_BASE + np.arange(n, dtype="int64")
    shared = rng.random(n) < SHARED_DEVICE_SHARE
    device[shared] = _GROUP_BASE + _group_ids(int(shared.sum()), rng)

    # --- VPA handle ---
    vpa = rng.choice(N_VPA_HANDLES, size=n, p=_zipf_weights(N_VPA_HANDLES, 0.8)).astype("int64")

    return pd.DataFrame(
        {
            "account": ordered,
            "derived_ip_id": ip,
            "derived_device_id": device,
            "derived_vpa_handle_id": vpa,
        }
    )


def attribute_degree(noise: pd.DataFrame, column: str) -> pd.Series:
    """Number of accounts sharing each account's value of `column` (aligned to noise rows)."""
    counts = noise[column].map(noise[column].value_counts())
    return counts.astype("int64")


def _two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def independence_report(noise: pd.DataFrame, flagged_accounts: set[str]) -> dict:
    """Compare ring accounts with all others on how hub-like their derived attributes are.

    For each attribute, the share of accounts on a shared value (degree > 1) is compared
    between the two groups with a two-proportion z-test. A label-blind layer should show no
    significant difference. For reporting only; nothing is tuned on this.
    """
    is_flagged = noise["account"].isin(flagged_accounts).to_numpy()
    n1, n0 = int(is_flagged.sum()), int((~is_flagged).sum())
    out: dict = {"n_flagged_accounts": n1, "n_other_accounts": n0, "attributes": {}}
    for column in ATTRIBUTE_COLUMNS:
        shared = (attribute_degree(noise, column) > 1).to_numpy()
        p1 = float(shared[is_flagged].mean()) if n1 else float("nan")
        p0 = float(shared[~is_flagged].mean()) if n0 else float("nan")
        pooled = float(shared.mean())
        denom = math.sqrt(pooled * (1 - pooled) * (1 / max(n1, 1) + 1 / max(n0, 1)))
        z = (p1 - p0) / denom if denom > 0 and n1 and n0 else 0.0
        out["attributes"][column] = {
            "share_on_shared_value_flagged": p1,
            "share_on_shared_value_other": p0,
            "z": z,
            "p_value": _two_sided_p(z),
        }
    out["min_p_value"] = min(v["p_value"] for v in out["attributes"].values())
    return out
