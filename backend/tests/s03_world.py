"""A small synthetic dataset in the real Stage 01 layout, for the Stage 03 tests.

Background accounts trade at random, one hub touches many accounts, and `n_rings` laundering
rings (directed 5-cycles, labelled illicit) appear evenly over time. A few illicit transfers
belong to no ring ("unringed"). Files written: events.parquet, split.parquet,
rings_truth.parquet in the processed folder of the given Settings.
"""

import numpy as np
import pandas as pd

T0 = pd.Timestamp("2022-09-01 00:00")


def make_world(seed=7, n_bg=300, n_rings=18, hours=240, n_unringed=24, n_transfers=6000):
    rng = np.random.default_rng(seed)
    rows = []  # (minute, src, dst, amount, illicit, ring_id)

    def add(minute, src, dst, amount, illicit=0, ring=np.nan):
        rows.append((int(minute), src, dst, float(amount), illicit, ring))

    bg = [f"b{i:03d}" for i in range(n_bg)]
    for _ in range(n_transfers):
        a, b = rng.choice(n_bg, size=2, replace=False)
        add(rng.integers(0, hours * 60), bg[a], bg[b], rng.lognormal(7, 1))
    for i in range(120):  # a hub that links many accounts
        add(rng.integers(0, hours * 60), "HUB", f"h{i:03d}", 50.0)
    for k in range(n_rings):
        members = [f"r{k:02d}_{i}" for i in range(5)]
        start = int((k + 0.5) / n_rings * hours * 0.9 * 60)
        for i in range(5):
            add(start + 50 * i, members[i], members[(i + 1) % 5],
                rng.lognormal(11, 0.3), 1, k + 1)  # fmt: skip
        for m in members:  # ring accounts also behave normally now and then
            for _ in range(2):
                add(rng.integers(0, hours * 60), m, bg[rng.integers(n_bg)], rng.lognormal(7, 1))
    for _ in range(n_unringed):
        a, b = rng.choice(n_bg, size=2, replace=False)
        add(rng.integers(0, hours * 60), bg[a], bg[b], rng.lognormal(9, 1), 1)

    frame = pd.DataFrame(rows, columns=["minute", "src", "dst", "amount", "illicit", "ring"])
    frame["event_id"] = np.arange(len(frame))
    frame = frame.sort_values(["minute", "event_id"], kind="stable").reset_index(drop=True)
    accounts = sorted(set(frame["src"]) | set(frame["dst"]))
    banks = [f"{i:03d}" for i in range(5)]
    n = len(frame)
    events = pd.DataFrame(
        {
            "event_id": frame["event_id"].astype("int64"),
            "ts": T0 + pd.to_timedelta(frame["minute"], unit="m"),
            "src_bank": pd.Categorical(rng.choice(banks, n), categories=banks),
            "src_account": pd.Categorical(frame["src"], categories=accounts),
            "dst_bank": pd.Categorical(rng.choice(banks, n), categories=banks),
            "dst_account": pd.Categorical(frame["dst"], categories=accounts),
            "amount_received": frame["amount"],
            "recv_currency": pd.Categorical(["Rupee"] * n, categories=["Euro", "Rupee"]),
            "amount_paid": frame["amount"],
            "pay_currency": pd.Categorical(["Rupee"] * n, categories=["Euro", "Rupee"]),
            "payment_format": pd.Categorical(
                rng.choice(["ACH", "Cheque", "Wire"], n), categories=["ACH", "Cheque", "Wire"]
            ),
            "amount_inr": frame["amount"],
            "ring_id": pd.array(frame["ring"].where(frame["ring"].notna(), pd.NA), dtype="Int32"),
            "is_illicit": frame["illicit"].astype("int8"),
        }
    )
    cut_train = events["ts"].quantile(0.6)
    cut_val = events["ts"].quantile(0.8)
    split = np.where(events["ts"] < cut_train, "train",
                     np.where(events["ts"] < cut_val, "val", "test"))  # fmt: skip
    split_frame = pd.DataFrame({"event_id": events["event_id"], "split": split})
    first = (
        events.assign(split=split)[events["ring_id"].notna()]
        .groupby("ring_id")["split"]
        .first()
    )
    rings_truth = pd.DataFrame(
        {"ring_id": first.index.astype("int64"), "ring_split": first.to_numpy()}
    )
    return events, split_frame, rings_truth


def write_world(settings, **kwargs):
    events, split, rings = make_world(**kwargs)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    events.to_parquet(settings.events_path, index=False)
    split.to_parquet(settings.split_path, index=False)
    rings.to_parquet(settings.rings_truth_path, index=False)
    return events, split, rings
