"""A SYNTHETIC data set in the Elliptic file layout, for tests and dry runs. Not real data.

It mimics only the layout and a few qualitative features (49 time steps, a hub transaction per
step, small illicit clusters, unlabelled nodes, a score shift late in the period). Numbers
produced from it say nothing about the real Elliptic results.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ringsentinel.elliptic import schema as sc


def write_synthetic_elliptic(
    raw_dir: Path, *, per_step: int = 90, seed: int = 11, shift_after: int = 43,
    cross_step_edges: int = 0, header_in_features: bool = False,
) -> dict:  # fmt: skip
    """Write the three CSV files into raw_dir; return simple facts about what was written."""
    rng = np.random.default_rng(seed)
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows, classes, edges = [], [], []
    next_id = 1_000_000
    illicit_total = 0
    first_ids: dict[int, int] = {}
    for step in range(1, 50):
        ids = np.arange(next_id, next_id + per_step)
        next_id += per_step
        first_ids[step] = int(ids[0])
        is_bad = rng.random(per_step) < 0.12
        known = rng.random(per_step) < 0.6
        clusters = np.flatnonzero(is_bad)
        for i, tx in enumerate(ids):
            feats = rng.normal(0, 1, sc.N_FEATURE_COLUMNS - 2)
            if is_bad[i]:
                feats[:6] += 1.6  # illicit transactions differ on a few local features
            if step > shift_after:
                feats[:6] += 1.2  # late shift of the very features the signal lives in
            rows.append([int(tx), step, *feats.tolist()])
            if not known[i]:
                classes.append((int(tx), sc.CLASS_UNKNOWN))
            else:
                classes.append((int(tx), sc.CLASS_ILLICIT if is_bad[i] else sc.CLASS_LICIT))
            illicit_total += int(is_bad[i] and known[i])
        for i in range(per_step - 1):  # a loose chain of payments among everyone
            if rng.random() < 0.7:
                edges.append((int(ids[i]), int(ids[rng.integers(i + 1, per_step)])))
        for a, b in zip(clusters[:-1], clusters[1:], strict=True):  # illicit nodes link up
            edges.append((int(ids[a]), int(ids[b])))
        for i in range(1, per_step, 2):  # a hub: one transaction paying many others
            edges.append((int(ids[0]), int(ids[i])))
    for k in range(cross_step_edges):
        step = 2 + k % 47
        edges.append((first_ids[step - 1] + 3 + k, first_ids[step] + 5 + k))
    with (raw_dir / sc.FEATURES_FILE).open("w", encoding="utf-8", newline="") as out:
        if header_in_features:
            out.write(",".join(["txId", "time_step", *[f"f{i}" for i in range(165)]]) + "\n")
        for r in rows:
            out.write(",".join([str(r[0]), str(r[1]), *[f"{v:.5f}" for v in r[2:]]]) + "\n")
    with (raw_dir / sc.CLASSES_FILE).open("w", encoding="utf-8", newline="") as out:
        out.write("txId,class\n")
        out.writelines(f"{t},{c}\n" for t, c in classes)
    with (raw_dir / sc.EDGELIST_FILE).open("w", encoding="utf-8", newline="") as out:
        out.write("txId1,txId2\n")
        out.writelines(f"{a},{b}\n" for a, b in edges)
    return {"nodes": len(rows), "edges": len(edges), "labelled_illicit": illicit_total}
