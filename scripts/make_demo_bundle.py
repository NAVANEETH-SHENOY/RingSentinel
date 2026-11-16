r"""Build the DEMO snapshot bundle used by the frontend when no real bundle is present.

Everything in it is invented: accounts, rings, scores, rupee amounts and every metric. It exists so
the interface can be developed, tested and shown before Stage 03 has produced real results, and the
interface marks it with a banner. It is valid against the real bundle schemas and loader.

Usage (repo root, cmd):  python scripts\make_demo_bundle.py [--out DIR] [--check]
"""

import argparse
import hashlib
import math
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ringsentinel.ai.pipeline import ai_document, build_ai_cases  # noqa: E402
from ringsentinel.monitor.drift import compute_drift  # noqa: E402
from ringsentinel.monitor.replay import compute_replay  # noqa: E402
from ringsentinel.snapshots.ai_merge import (  # noqa: E402
    AI_SOURCE_NAME,
    ai_document_hash,
    apply_ai_blocks,
)
from ringsentinel.snapshots.bundle import (  # noqa: E402
    DATA_FILES,
    SnapshotError,
    bundle_id_from,
    canonical_text,
    clean,
    load_bundle,
    sha256_bytes,
)
from ringsentinel.snapshots.export import (  # noqa: E402
    expected_value_inr,
    ring_id_for,
    write_bundle,
)
from ringsentinel.snapshots.schemas import SCHEMA_VERSION  # noqa: E402

DEFAULT_OUT = ROOT / "frontend" / "public" / "demo-snapshots"
DETECTOR = "demo_detector"
COST = {"review_cost_inr": 250.0, "fp_cost_inr": 500.0, "loss_capture_rate": 1.0,
        "note": "DEMO values, not a measurement."}  # fmt: skip
DEMO_NOTE = "DEMO: every number in this bundle is invented for interface development."
FEATURES = ["comm_density", "fan_ratio", "burst_share", "cycles3", "pagerank", "comm_size"]


def _account(rng: random.Random) -> str:
    return "8" + "".join(rng.choice("0123456789ABCDEF") for _ in range(8))


def _accounts(rng: random.Random, n: int, used: set[str]) -> list[str]:
    out: list[str] = []
    while len(out) < n:
        a = _account(rng)
        if a not in used:
            used.add(a)
            out.append(a)
    return out


def _edges(rng: random.Random, pairs: list[tuple[str, str]], day: int) -> list[dict]:
    edges = []
    for i, (src, dst) in enumerate(pairs):
        n = rng.randint(1, 4)
        total = round(rng.uniform(2_000, 90_000) * n, 2)
        start = f"2022-09-{day:02d}T{(i * 7) % 24:02d}:{(i * 13) % 60:02d}:00"
        end = (
            f"2022-09-{min(day + rng.randint(0, 2), 28):02d}"
            f"T{(i * 5 + 3) % 24:02d}:{(i * 11) % 60:02d}:00"
        )
        edges.append({"src": src, "dst": dst, "n_transfers": n, "total_inr": total,
                      "first_ts": start, "last_ts": max(start, end)})  # fmt: skip
    edges.sort(key=lambda e: (-e["total_inr"], e["src"], e["dst"]))
    return edges


def _shape(kind: str, rng: random.Random, accts: list[str]) -> list[tuple[str, str]]:
    if kind == "cycle":
        return [(accts[i], accts[(i + 1) % len(accts)]) for i in range(len(accts))]
    if kind == "fan_in":
        return [(a, accts[0]) for a in accts[1:]]
    if kind == "fan_out":
        return [(accts[0], a) for a in accts[1:]]
    if kind == "scatter_gather":
        mid = accts[1:-1]
        return [(accts[0], m) for m in mid] + [(m, accts[-1]) for m in mid]
    if kind == "bipartite":
        half = len(accts) // 2
        return [(a, b) for a in accts[:half] for b in accts[half : half + 3]]
    return [(accts[i], accts[i + 1]) for i in range(len(accts) - 1)]  # stack / chain


RING_SPECS = [  # kind, accounts, score
    ("scatter_gather", 12, 0.93), ("cycle", 6, 0.91), ("fan_in", 9, 0.88), ("fan_out", 10, 0.84),
    ("stack", 7, 0.8), ("bipartite", 10, 0.77), ("cycle", 8, 0.7), ("fan_in", 6, 0.66),
    ("stack", 5, 0.58), ("scatter_gather", 8, 0.52), ("fan_out", 5, 0.47), ("cycle", 4, 0.41),
    ("stack", 4, 0.33),
]  # fmt: skip


def _ring_records(rng: random.Random) -> list[dict]:
    used: set[str] = set()
    records = []
    for idx, (kind, n, score) in enumerate(RING_SPECS):
        accts = _accounts(rng, n, used)
        edges = _edges(rng, _shape(kind, rng, accts), 1 + idx % 9)
        records.append({"members": accts, "n_members": n, "score": score, "edges": edges,
                        "n_transfers": sum(e["n_transfers"] for e in edges),
                        "oversized": False})  # fmt: skip
    # One ring bigger than the 500-account display cap: 640 accounts, member list cut to 500 and
    # 500 transfer links (the exporter's own limits), spread over ~700 distinct accounts.
    big = _accounts(rng, 700, used)
    pairs = []
    for i in range(500):
        pairs.append(
            (big[i % 640], big[(i * 7 + 3) % 700]) if i % 5 else (big[i % 640], big[(i + 1) % 640])
        )
    pairs = sorted({p for p in pairs if p[0] != p[1]})[:500]
    edges = _edges(rng, pairs, 4)
    records.append(
        {
            "members": sorted(big[:500]),
            "n_members": 640,
            "score": 0.74,
            "edges": edges,
            "n_transfers": sum(e["n_transfers"] for e in edges) + 400,
            "oversized": True,
        }
    )
    for r in records:
        r["amount_inr"] = round(math.fsum(e["total_inr"] for e in r["edges"]) * 1.1, 2)
        r["top_features"] = [
            {"feature": FEATURES[(j + int(r["score"] * 10)) % len(FEATURES)],
             "mean_contribution": round(0.9 / (j + 1.5), 4)}
            for j in range(5)
        ]  # fmt: skip
    return records


def _metrics() -> dict:
    names = ["velocity", "xgb_tabular", "xgb_graph", "iforest"]
    base = {"velocity": 0.002, "xgb_tabular": 0.031, "xgb_graph": 0.047, "iforest": 0.004}
    detectors = {}
    for n in names:
        auc = base[n]
        curve = [
            {
                "recall": round(r / 10, 2),
                "precision": round(max(0.0, 0.9 * auc * 10 ** (1 - r / 10) / 10 * 4), 4),
            }
            for r in range(0, 11)
        ]
        detectors[n] = {
            "val": {"pr_auc": round(auc * 0.9, 4), "positives": 900, "prevalence": 0.00107},
            "test": {
                "pr_auc": auc,
                "positives": 1500,
                "prevalence": 0.00177,
                "ring_pr_tau_0.5": curve,
            },  # fmt: skip
        }
    sweep = {
        n: [
            {
                "capture": c,
                "review_cost_inr": rv,
                "fp_cost_inr": fp,
                "threshold": 0.5,
                "test_net_value_inr": round(
                    (base[n] * 4e6 * c)
                    - rv * (40 - 10 * base[n] * 10)
                    - fp * 25 * (1 + base[n] * 3)
                ),
                "rings_flagged": 20,
            }  # fmt: skip
            for c in (0.5, 0.75, 1.0)
            for rv in (100.0, 250.0, 500.0)
            for fp in (250.0, 500.0, 1000.0, 2000.0)
        ]
        for n in names
    }
    table = (
        "DEMO (invented numbers)\n\n| detector | test PR-AUC | ring F1 (tau 0.5) | net value |\n"
        "| --- | --- | --- | --- |\n"
        + "\n".join(
            f"| {n} | {base[n]:.4f} | {base[n] * 3:.3f} | ₹{int(base[n] * 1e6):,} |" for n in names
        )
        + "\n"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "dataset_variant": "DEMO-SYNTHETIC",
            "seed": 20260101,
            "note": DEMO_NOTE,
            "cost_assumptions_inr": COST,
        },  # fmt: skip
        "detectors": detectors,
        "cost_sweep": sweep,
        "ablations": {
            "variants": {
                "xgb_tabular": {
                    "label": "Tabular only",
                    "summary": {"test_pr_auc": 0.031, "ring_f1": 0.09},
                },
                "xgb_graph_nohub": {
                    "label": "Graph, hub control off",
                    "summary": {"test_pr_auc": 0.039, "ring_f1": 0.12},
                },
                "xgb_graph": {
                    "label": "Graph, hub control on",
                    "summary": {"test_pr_auc": 0.047, "ring_f1": 0.14},
                },
            }
        },  # fmt: skip
        "robustness": {
            "levels": [
                {
                    "dropout": d,
                    "events_kept": int(1_000_000 * (1 - d)),
                    "test_pr_auc": round(0.047 * (1 - d) ** 1.5, 4),
                    "pr_auc_relative_to_no_dropout": round((1 - d) ** 1.5, 4),
                    "rings_at_f1_threshold": int(40 * (1 - d)),
                    "rings_at_nv_threshold": int(14 * (1 - d)),
                }  # fmt: skip
                for d in (0.0, 0.1, 0.2, 0.3, 0.5)
            ]
        },  # fmt: skip
        "latency": {
            n: {
                "threshold": 0.5,
                "rings_with_flag": 12,
                "events_median": 800 + i * 150,
                "events_p90": 2400 + i * 300,
                "minutes_median": 300 + i * 40,
                "minutes_p90": 1500 + i * 100,
            }
            for i, n in enumerate(names)
        },  # fmt: skip
        "results_table_md": table,
    }


def _ns(text: str) -> int:
    return int(np.datetime64(text, "ns").astype("int64"))


def _demo_drift(threshold: float) -> dict:
    """Real PSI code on invented scores: calm for five windows, then the scores slide upward."""
    rng = np.random.default_rng(7)
    reference = rng.beta(1.2, 18.0, 3000)
    n_test, t0, t1 = 6000, _ns("2022-09-01T00:00:00"), _ns("2022-09-14T00:00:00")
    ts = np.sort(rng.integers(t0, t1, n_test))
    position = (ts - t0) / (t1 - t0)
    shift = np.clip((position - 0.6) / 0.4, 0.0, 1.0)  # 0 for the first 60 percent of the time
    scores = np.where(
        rng.random(n_test) < shift,
        rng.beta(2.6, 9.0, n_test),
        rng.beta(1.2, 18.0, n_test),
    )
    labels = (rng.random(n_test) < np.clip(scores * 0.12, 0.0, 1.0)).astype("int64")
    return compute_drift(
        reference, scores, ts, labels, threshold, detector=DETECTOR, n_windows=8, n_bins=10,
        warn_level=0.10, alert_level=0.25, min_events=500,
    )  # fmt: skip


def _ring_transfers(rec: dict, rid: str, event_id: int) -> tuple[dict, int]:
    """Spread each linked pair's transfers between its first and last timestamp."""
    ts, src, dst, ids = [], [], [], []
    for edge in rec["edges"]:
        a, b = _ns(edge["first_ts"]), _ns(edge["last_ts"])
        n = edge["n_transfers"]
        for k in range(n):
            ts.append(a + (b - a) * k // max(n - 1, 1))
            src.append(edge["src"])
            dst.append(edge["dst"])
            ids.append(event_id)
            event_id += 1
    return {"ts_ns": ts, "src": src, "dst": dst, "event_id": ids}, event_id


def _demo_replay(ranked: list, threshold: float) -> dict:
    """Real replay code on the invented rings. Three rings carry an invented 'true' ring id."""
    rng = np.random.default_rng(11)
    t0, t1 = _ns("2022-09-01T00:00:00"), _ns("2022-09-14T00:00:00")
    test_ts = np.sort(rng.integers(t0, t1, 6000))
    rings, ring_events, truth_first = [], {}, {}
    event_id = 1
    for rank, (rid, value, rec) in enumerate(ranked[:10], start=1):
        data, event_id = _ring_transfers(rec, rid, event_id)
        truth = 900 + rank if rank in (1, 3, 6) else -1
        data["truth_id"] = [truth] * len(data["ts_ns"])
        if truth >= 0:
            truth_first[truth] = min(data["ts_ns"]) - (rank * 17 + 40) * 60 * 10**9
        ring_events[rid] = data
        rings.append({"ring_id": rid, "rank": rank, "score": rec["score"],
                      "expected_value_inr": value, "n_members": rec["n_members"],
                      "n_transfers": rec["n_transfers"]})  # fmt: skip
    return compute_replay(
        rings, ring_events, test_ts, truth_first, detector=DETECTOR, threshold=threshold,
        min_size=3, n_steps=96,
    )  # fmt: skip


def _with_template_ai(cases: dict) -> dict:
    """Offline template case files for every demo case, built by the real AI code path."""
    blocks, _ = build_ai_cases(cases, None, None)
    return ai_document(blocks)


def build_demo_documents() -> dict[str, dict]:
    rng = random.Random(20260101)
    records = _ring_records(rng)
    review, fp, capture = COST["review_cost_inr"], COST["fp_cost_inr"], COST["loss_capture_rate"]
    ranked = []
    for rec in records:
        rid = ring_id_for(DETECTOR, rec["members"])
        value = expected_value_inr(
            rec["score"], rec["amount_inr"], rec["n_members"], review, fp, capture
        )
        ranked.append((rid, value, rec))
    ranked.sort(key=lambda r: (-r[1], r[0]))
    items, cases = [], {}
    for rank, (rid, value, rec) in enumerate(ranked, start=1):
        common = {"ring_id": rid, "rank": rank, "score": rec["score"], "expected_value_inr": value,
                  "amount_inr": rec["amount_inr"], "n_members": rec["n_members"],
                  "n_transfers": rec["n_transfers"], "oversized": rec["oversized"]}  # fmt: skip
        items.append({**common, "top_features": rec["top_features"][:3]})
        cases[rid] = {**common, "members": sorted(rec["members"]),
                      "members_truncated": rec["n_members"] > len(rec["members"]),
                      "top_features": rec["top_features"], "edges": rec["edges"],
                      "edges_available": True,
                      "edges_truncated": rec["n_transfers"] > sum(
                          e["n_transfers"] for e in rec["edges"]
                      ),
                      "ai": {"status": "not_built", "built_in_stage": "06", "investigator": None,
                             "verifier": None, "benign_explanation": None}}  # fmt: skip
    docs = {
        "queue.json": {
            "schema_version": SCHEMA_VERSION,
            "detector": DETECTOR,
            "split": "test",
            "threshold": 0.3,
            "threshold_kind": "DEMO threshold",
            "score_calibrated": False,
            "value_formula": (
                "expected_value_inr = score * loss_capture_rate * amount_inr "
                "- review_cost_inr - fp_cost_inr * n_members * (1 - score). "
                "DEMO data; the score is not a calibrated probability."
            ),
            "cost_assumptions": COST,
            "note": DEMO_NOTE,
            "items": items,
        },  # fmt: skip
        "cases.json": {"schema_version": SCHEMA_VERSION, "cases": cases},
        "metrics.json": _metrics(),
        "drift.json": _demo_drift(0.3),
        "replay.json": _demo_replay(ranked, 0.3),
    }
    ai_doc = _with_template_ai(cases)
    apply_ai_blocks(cases, ai_doc)
    file_hashes = {
        n: sha256_bytes(canonical_text(clean(docs[n])).encode("utf-8")) for n in DATA_FILES
    }
    source_names = (
        "rings.json",
        "metrics.json",
        "ablations.json",
        "robustness.json",
        "latency.json",
    )
    sources = {n: hashlib.sha256(f"demo:{n}".encode()).hexdigest() for n in source_names}
    sources[AI_SOURCE_NAME] = ai_document_hash(ai_doc)
    docs["meta.json"] = {
        "schema_version": SCHEMA_VERSION, "bundle_id": bundle_id_from(file_hashes),
        "dataset_variant": "DEMO-SYNTHETIC",
        "seed": 20260101,
        "git_commit": "demo",
        "evaluation_frozen": False,
        "detector": DETECTOR, "split": "test", "n_rings_total": len(ranked),
        "n_rings_exported": len(ranked), "max_rings": 500, "sources": sources, "files": file_hashes,
    }  # fmt: skip
    return docs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--check", action="store_true", help="fail if --out differs from a fresh build"
    )
    args = parser.parse_args(argv)
    docs = clean(build_demo_documents())
    if args.check:
        for name, doc in docs.items():
            path = args.out / name
            if not path.is_file() or path.read_bytes() != canonical_text(doc).encode("utf-8"):
                print(f"DEMO BUNDLE STALE: {name} differs. Run scripts\\make_demo_bundle.py")
                return 1
        print("demo bundle is up to date")
        return 0
    write_bundle(docs, args.out)
    try:
        bundle = load_bundle(args.out)
    except SnapshotError as exc:
        print(f"DEMO BUNDLE INVALID: {exc}")
        return 1
    print(
        f"demo bundle written to {args.out} "
        f"(bundle_id {bundle.bundle_id[:12]}, "
        f"{bundle.meta['n_rings_exported']} rings)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
