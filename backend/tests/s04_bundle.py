"""Hand-made Stage 03 outputs (tiny, exact numbers) for the Stage 04 tests."""

import json

import pandas as pd

COST = {"review_cost_inr": 250.0, "fp_cost_inr": 500.0, "loss_capture_rate": 1.0, "note": "t"}

# (members, score, amount_inr, event_ids); expected values at the default costs:
#   A = 0.9*100000 - 250 - 500*3*0.1 = 89600.0     B = 0.5*20000 - 250 - 500*4*0.5 = 8750.0
#   C = 0.1*1000   - 250 - 500*3*0.9 = -1500.0
RINGS = {
    "A": (["a1", "a2", "a3"], 0.9, 100000.0, [1, 2, 3]),
    "B": (["b1", "b2", "b3", "b4"], 0.5, 20000.0, [4, 5]),
    "C": (["c1", "c2", "c3"], 0.1, 1000.0, [6]),
}
EXPECTED_VALUES = {"A": 89600.0, "B": 8750.0, "C": -1500.0}


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def write_stage03_outputs(settings, rings=None, with_events=True, threshold=0.04):
    rings = RINGS if rings is None else rings
    entries = []
    for i, (members, score, amount, event_ids) in enumerate(rings.values()):
        entries.append(
            {
                "ring_index": i, "score": score, "n_members": len(members),
                "n_transfers": len(event_ids), "amount_inr": amount, "oversized": False,
                "members": members, "event_ids": event_ids,
                "top_features": [
                    {"feature": f"f{j}", "mean_contribution": 1.0 / (j + 1)} for j in range(5)
                ],
            }
        )  # fmt: skip
    _write(
        settings.rings_path,
        {
            "detector": "xgb_graph", "split": "test", "threshold": threshold,
            "threshold_kind": "net_value (chosen on validation)", "rings": entries,
        },
    )  # fmt: skip
    _write(
        settings.metrics_path,
        {
            "meta": {"dataset_variant": "HI-Small", "seed": 42, "cost_assumptions_inr": COST},
            "detectors": {"xgb_graph": {"test": {"pr_auc": 0.5}}},
            "cost_sweep": [{"review": 250.0, "fp": 500.0, "capture": 1.0}],
        },
    )  # fmt: skip
    _write(settings.ablations_path, {"variants": {}})
    _write(settings.robustness_path, {"levels": []})
    _write(settings.latency_path, {"xgb_graph": {"share_detected": 1.0}})
    settings.results_table_path.write_text("| detector |\n|---|\n", encoding="utf-8")
    if with_events:
        write_events(settings)


def write_events(settings):
    accounts = ["a1", "a2", "a3", "b1", "b2", "b3", "b4", "c1", "c2", "c3"]
    rows = [  # event_id, ts, src, dst, amount
        (1, "2022-09-01 10:00", "a1", "a2", 100.0),
        (2, "2022-09-01 11:00", "a1", "a2", 50.0),
        (3, "2022-09-01 12:00", "a2", "a3", 10.0),
        (4, "2022-09-02 10:00", "b1", "b2", 30.0),
        (5, "2022-09-02 11:00", "b3", "b4", 20.0),
        (6, "2022-09-03 10:00", "c1", "c2", 5.0),
        (7, "2022-09-03 10:00", "c2", "c3", 7.0),
    ]
    cols = ["event_id", "ts", "src_account", "dst_account", "amount_inr"]
    frame = pd.DataFrame(rows, columns=cols)
    frame["ts"] = pd.to_datetime(frame["ts"])
    for col in ("src_account", "dst_account"):
        frame[col] = pd.Categorical(frame[col], categories=accounts)
    settings.processed_dir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(settings.events_path, index=False)
