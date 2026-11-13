"""Run Stage 02 from the command line (repo root, venv active; Stage 01 outputs must exist).

    python scripts\\run_stage02.py                    # noise, tune, features, ablation
    python scripts\\run_stage02.py --step tune        # one step only
    python scripts\\run_stage02.py --step features --window val

Steps: noise (D3), tune (hub cap on validation), features (D5 + D6), ablation.
The hub cap is RS_HUB_CAP if set, else the tuned value, else 50.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.stage02 import (  # noqa: E402
    WINDOWS,
    format_ablation,
    run_ablation,
    run_features,
    run_noise,
    run_tune,
)

STEPS = ("noise", "tune", "features", "ablation")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", choices=(*STEPS, "all"), default="all")
    parser.add_argument("--window", choices=WINDOWS, help="features/ablation for one window")
    args = parser.parse_args(argv)
    settings = get_settings()
    wanted = STEPS if args.step == "all" else (args.step,)
    windows = (args.window,) if args.window else WINDOWS
    print(f"Variant: {settings.dataset_variant}   data dir: {settings.data_dir}")

    for needed in (settings.events_path, settings.split_path, settings.rings_truth_path):
        if not needed.exists():
            print(f"Missing {needed}. Run scripts\\run_stage01.py first.")
            return 1

    if "noise" in wanted:
        report = run_noise(settings)
        ind = report["independence_of_ring_membership"]
        print(f"Noise: {report['accounts']:,} accounts; min independence p-value "
              f"{ind['min_p_value']:.3f}")  # fmt: skip
        print(f"Saved: {settings.noise_path}")
    if "tune" in wanted:
        tuned = run_tune(settings)
        print("Hub-cap tuning (validation window):")
        for row in tuned["table"]:
            print(f"  cap {row['cap']:>5}: hubs {row['hub_nodes']:>6,}  "
                  f"ring-account retention {row['ring_account_retention']:.3f}")  # fmt: skip
        print(f"Chosen cap: {tuned['chosen_cap']}  ({tuned['rule']})")
    if "features" in wanted:
        out = run_features(settings, windows)
        print(f"Features: hub cap {out['hub_cap']}, rows {out['rows']}, columns {out['columns']}")
        for w in windows:
            c = out["communities"][w]
            linked = c["giant_component_fraction_of_linked_accounts"]
            print(
                f"  {w}: giant component {linked:.1%} of linked accounts, "
                f"communities {c['communities']:,}, oversized {c['oversized_flagged']}, "
                f"hubs dropped {out['pruning'][w]['hub_nodes_dropped']}"
            )
            diag = c.get("ring_recovery_diagnostic")
            if diag:
                print(
                    f"    ring recovery (reporting only): {diag['rings']} rings, median "
                    f"Jaccard {diag['median_jaccard']:.3f}, share >= 0.5: "
                    f"{diag['share_jaccard_ge_0.5']:.3f}, all accounts in one community: "
                    f"{diag['share_all_accounts_in_one_community']:.3f}"
                )
        print(f"Saved: {settings.features_path}")
    if "ablation" in wanted:
        result = run_ablation(settings, windows)
        print(format_ablation(result))
        print(f"Saved: {settings.ablation_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
