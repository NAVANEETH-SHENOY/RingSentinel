"""Snapshot exporter (data stage D12): Stage 03 outputs in, a small validated JSON bundle out.

The bundle is deterministic: the same input files and options give byte-identical output. There
are no timestamps; the git commit is passed in. Drift and replay are not built until Stage 07 and
the case-file AI layer until Stage 06, so those parts are exported as explicit placeholders.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from ringsentinel.config import Settings
from ringsentinel.snapshots.bundle import (
    DATA_FILES,
    Bundle,
    SnapshotError,
    bundle_id_from,
    canonical_text,
    clean,
    load_bundle,
    sha256_bytes,
)
from ringsentinel.snapshots.schemas import SCHEMA_VERSION

DEFAULT_MAX_RINGS = 500
MAX_EDGES_PER_CASE = 500
QUEUE_TOP_FEATURES = 3
VALUE_FORMULA = (
    "expected_value_inr = score * loss_capture_rate * amount_inr - review_cost_inr "
    "- fp_cost_inr * n_members * (1 - score). The score is an uncalibrated model output used as "
    "a stand-in for the chance the ring is real, so this is a ranking heuristic, not a forecast."
)
SOURCE_FILES = ("rings.json", "metrics.json", "ablations.json", "robustness.json", "latency.json")


def ring_id_for(detector: str, members: list[str]) -> str:
    """Stable id from the detector name and the sorted member accounts (cacheable by hash)."""
    text = detector + "\n" + "\n".join(sorted(members))
    return "R-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def expected_value_inr(
    score: float, amount_inr: float, n_members: int, review_cost: float, fp_cost: float,
    capture: float,
) -> float:  # fmt: skip
    """Ranking value of reviewing one ring (see VALUE_FORMULA). Rounded to paise."""
    value = score * capture * amount_inr - review_cost - fp_cost * n_members * (1.0 - score)
    return round(value, 2)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise SnapshotError(f"Stage 03 output missing: {path}. Run scripts/run_stage03.py first.")
    return json.loads(path.read_text(encoding="utf-8"))


def _edges_by_ring(rings: list[dict], events_path: Path | None) -> dict[int, list[dict]] | None:
    """Aggregate each ring's own transfers into account-to-account edges (None if no events)."""
    if events_path is None or not events_path.is_file():
        return None
    wanted = sorted({int(e) for r in rings for e in r["event_ids"]})
    if not wanted:
        return {}
    columns = ["event_id", "ts", "src_account", "dst_account", "amount_inr"]
    frame = pd.read_parquet(events_path, columns=columns, filters=[("event_id", "in", wanted)])
    frame = frame.assign(
        src_account=frame["src_account"].astype(str), dst_account=frame["dst_account"].astype(str)
    ).set_index("event_id")
    out: dict[int, list[dict]] = {}
    for index, ring in enumerate(rings):
        ids = [int(e) for e in ring["event_ids"] if int(e) in frame.index]
        sub = frame.loc[ids]
        grouped = sub.groupby(["src_account", "dst_account"], sort=True).agg(
            n_transfers=("amount_inr", "size"), total_inr=("amount_inr", "sum"),
            first_ts=("ts", "min"), last_ts=("ts", "max"),
        )  # fmt: skip
        edges = [
            {
                "src": src, "dst": dst, "n_transfers": int(row.n_transfers),
                "total_inr": round(float(row.total_inr), 2),
                "first_ts": pd.Timestamp(row.first_ts).isoformat(),
                "last_ts": pd.Timestamp(row.last_ts).isoformat(),
            }
            for (src, dst), row in grouped.iterrows()
        ]  # fmt: skip
        edges.sort(key=lambda e: (-e["total_inr"], e["src"], e["dst"]))
        out[index] = edges
    return out


def build_documents(
    settings: Settings, *, git_commit: str = "unknown", frozen: bool = False,
    max_rings: int = DEFAULT_MAX_RINGS, events_path: Path | None = None,
) -> tuple[dict[str, dict], dict[str, str]]:  # fmt: skip
    """Build the six bundle documents in memory. Returns (documents, source file hashes)."""
    if max_rings < 1:
        raise ValueError("max_rings must be at least 1")
    sources = {
        "rings.json": settings.rings_path, "metrics.json": settings.metrics_path,
        "ablations.json": settings.ablations_path, "robustness.json": settings.robustness_path,
        "latency.json": settings.latency_path,
    }  # fmt: skip
    payload = {name: _read_json(path) for name, path in sources.items()}
    source_hashes = {name: sha256_bytes(path.read_bytes()) for name, path in sources.items()}
    rings_doc, metrics_doc = payload["rings.json"], payload["metrics.json"]
    detector = rings_doc["detector"]
    cost = metrics_doc["meta"]["cost_assumptions_inr"]
    review, fp, capture = cost["review_cost_inr"], cost["fp_cost_inr"], cost["loss_capture_rate"]

    ranked = []
    for ring in rings_doc["rings"]:
        members = list(ring["members"])
        rid = ring_id_for(detector, members)
        value = expected_value_inr(
            ring["score"], ring["amount_inr"], ring["n_members"], review, fp, capture
        )
        ranked.append((rid, value, ring))
    ids = [r[0] for r in ranked]
    if len(set(ids)) != len(ids):
        raise SnapshotError("two rings produced the same ring_id")
    ranked.sort(key=lambda r: (-r[1], r[0]))
    kept = ranked[:max_rings]
    edges = _edges_by_ring([r[2] for r in kept], events_path)

    items, cases = [], {}
    for rank, (rid, value, ring) in enumerate(kept, start=1):
        top = [
            {"feature": f["feature"], "mean_contribution": f["mean_contribution"]}
            for f in ring.get("top_features", [])
        ]
        common = {
            "ring_id": rid, "rank": rank, "score": ring["score"], "expected_value_inr": value,
            "amount_inr": ring["amount_inr"], "n_members": ring["n_members"],
            "n_transfers": ring["n_transfers"], "oversized": bool(ring["oversized"]),
        }  # fmt: skip
        items.append({**common, "top_features": top[:QUEUE_TOP_FEATURES]})
        ring_edges = edges[rank - 1] if edges is not None else []
        cases[rid] = {
            **common,
            "members": sorted(ring["members"]),
            "members_truncated": ring["n_members"] > len(ring["members"]),
            "top_features": top,
            "edges": ring_edges[:MAX_EDGES_PER_CASE],
            "edges_available": edges is not None,
            "edges_truncated": len(ring_edges) > MAX_EDGES_PER_CASE
            or ring["n_transfers"] > len(ring["event_ids"]),
            "ai": {
                "status": "not_built", "built_in_stage": "06", "investigator": None,
                "verifier": None, "benign_explanation": None,
            },
        }  # fmt: skip
    queue = {
        "schema_version": SCHEMA_VERSION, "detector": detector, "split": rings_doc["split"],
        "threshold": rings_doc["threshold"], "threshold_kind": rings_doc["threshold_kind"],
        "score_calibrated": False, "value_formula": VALUE_FORMULA, "cost_assumptions": cost,
        "items": items,
    }  # fmt: skip
    if "note" in rings_doc:
        queue["note"] = rings_doc["note"]
    table_path = settings.results_table_path
    metrics = {
        "schema_version": SCHEMA_VERSION, "meta": metrics_doc["meta"],
        "detectors": metrics_doc["detectors"], "cost_sweep": metrics_doc["cost_sweep"],
        "ablations": payload["ablations.json"], "robustness": payload["robustness.json"],
        "latency": payload["latency.json"],
        "results_table_md": (
            table_path.read_text(encoding="utf-8") if table_path.is_file() else None
        ),
    }  # fmt: skip
    drift = {
        "schema_version": SCHEMA_VERSION, "status": "not_built", "built_in_stage": "07",
        "psi_alert_level": None, "windows": [],
    }  # fmt: skip
    replay = {
        "schema_version": SCHEMA_VERSION, "status": "not_built", "built_in_stage": "07",
        "events": [],
    }  # fmt: skip
    docs = {
        "queue.json": queue, "cases.json": {"schema_version": SCHEMA_VERSION, "cases": cases},
        "metrics.json": metrics, "drift.json": drift, "replay.json": replay,
    }  # fmt: skip
    file_hashes = {n: sha256_bytes(canonical_text(docs[n]).encode("utf-8")) for n in DATA_FILES}
    docs["meta.json"] = {
        "schema_version": SCHEMA_VERSION, "bundle_id": bundle_id_from(file_hashes),
        "dataset_variant": metrics_doc["meta"]["dataset_variant"],
        "seed": metrics_doc["meta"]["seed"], "git_commit": git_commit,
        "evaluation_frozen": frozen, "detector": detector, "split": rings_doc["split"],
        "n_rings_total": len(ranked), "n_rings_exported": len(kept), "max_rings": max_rings,
        "sources": source_hashes, "files": file_hashes,
    }  # fmt: skip
    return docs, source_hashes


def write_bundle(docs: dict[str, dict], out_dir: Path) -> None:
    """Write all six files (UTF-8, LF newlines). Existing bundle files are replaced."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, doc in docs.items():
        with (out_dir / name).open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_text(doc))


def export_snapshots(
    settings: Settings, out_dir: Path | None = None, *, git_commit: str = "unknown",
    frozen: bool = False, max_rings: int = DEFAULT_MAX_RINGS, with_edges: bool = True,
) -> Bundle:  # fmt: skip
    """Build, write and re-load (schema, hash and cross-reference check) the bundle."""
    out_dir = Path(out_dir) if out_dir is not None else settings.snapshots_dir
    events_path = settings.events_path if with_edges else None
    docs, _ = build_documents(
        settings, git_commit=git_commit, frozen=frozen, max_rings=max_rings,
        events_path=events_path,
    )  # fmt: skip
    write_bundle(clean(docs), out_dir)
    return load_bundle(out_dir)
