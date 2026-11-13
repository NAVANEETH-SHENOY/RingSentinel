"""Tiny hand-built event tables for the Stage 02 tests."""

import pandas as pd

T0 = pd.Timestamp("2022-09-01 00:00")


def make_events(rows):
    """rows: (src, dst, minutes_from_start, amount_inr[, split])."""
    cols = ["src_account", "dst_account", "minute", "amount_inr", "split"]
    frame = pd.DataFrame(
        [(*r, "train") if len(r) == 4 else r for r in rows], columns=cols
    )
    frame["ts"] = T0 + pd.to_timedelta(frame.pop("minute"), unit="m")
    return frame[["src_account", "dst_account", "ts", "amount_inr", "split"]]


def hub_world(n_spokes=25):
    """A directed 3-cycle a1>a2>a3>a1, a hub H with n_spokes spokes plus a link to a1,
    a two-way pair p1<>p2 and one self-transfer of p1."""
    rows = [("a1", "a2", 1, 100.0), ("a2", "a3", 2, 100.0), ("a3", "a1", 3, 100.0)]
    rows += [("H", f"s{i:02d}", 10 + i, 10.0) for i in range(n_spokes)]
    rows += [("H", "a1", 100, 10.0)]
    rows += [("p1", "p2", 5, 50.0), ("p2", "p1", 6, 25.0), ("p1", "p1", 7, 9.0)]
    return make_events(rows)
