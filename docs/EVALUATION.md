# Evaluation protocol (Stage 03)

**Status: the protocol is fixed and implemented. No number in this project is frozen yet.** Stage 03 was built and tested on synthetic data; the sandbox cannot reach the real files. The numbers are produced by the owner running `scripts/reproduce.py`, which writes `docs/EVALUATION_RESULTS.md` [generated] (and `metrics.json` [generated] and the other result files). Until then, nothing here is a result.

After the Stage 03 tag (v0.4.0), changing a detector, a feature, a threshold rule or a cost assumption means rerunning `scripts/reproduce.py` and replacing every number.

## 1. Protocol

1. **Windows.** Features come from cumulative past-only windows (Stage 02): train rows use the train window, validation rows the validation window, test rows the test window. A transfer is described by the graph features of its sender and its receiver (two sets of 36 columns), plus its own tabular columns.
2. **Fitting** uses train rows only. Early stopping and every threshold use validation rows only. The test split is scored once per detector at thresholds fixed on validation. `SplitVault` in `backend/ringsentinel/detect/guard.py` enforces this: fitting code is given a view that has no test entry, and releasing the test split a second time for the same detector raises. A test rewrites the test split (labels flipped, amounts multiplied) and checks that every validation score and every saved model file is byte-identical; a companion test applies the same rewrite to validation and checks that results do move, so the guard is shown to have power.
3. **Training sample.** All positive rows and a seeded share (`RS_NEG_SAMPLE_FRAC`, default 0.2) of negative rows are used to fit XGBoost, to bound memory. Scoring always covers every row of the split. Thresholds are chosen on the full validation split, so the sampling does not bias them.
4. **Reproducibility.** XGBoost uses one thread and a fixed seed; the Isolation Forest is seeded; ring extraction and Louvain are seeded and use sorted order. Same machine and inputs give identical numbers (`scripts/reproduce.py` checks this against the previous run). Stage 01 saw platform differences in XGBoost (Windows versus Linux); quote the platform next to any number.

## 2. Detectors (all score each transfer, higher is more suspicious)

| Name | What it is | Fitted on |
| --- | --- | --- |
| `velocity` | Number of transfers the sender made in the trailing 24 hours (strictly earlier minutes). No fitting | none |
| `xgb_tabular` | XGBoost on the transfer's own columns and the sender and receiver trailing 24-hour counts (8 columns) | train |
| `xgb_graph` | The same XGBoost on those 8 columns plus the Stage 02 node and community features of both accounts (the contribution) | train |
| `iforest` | Isolation Forest on the `xgb_graph` columns (median-imputed), unsupervised, 200,000 uniformly sampled train rows, label-blind | train, no labels |

The Stage 03 velocity rule and tabular XGBoost are re-implemented here so that every detector goes through the same code path and the same test protocol. They are close to, but not byte-identical with, the Stage 01 baselines (different feature list and XGBoost settings). `detect_report.json` [generated] stores the Stage 01 reference numbers next to the new validation PR-AUCs so a reader can see how far apart they are; do not mix the two sets of numbers in one table.

## 3. Operating points

- **F1 threshold:** the score that maximises F1 on validation (fewest flags on ties). Transaction-level precision, recall and F1 on test use it.
- **Net-value threshold:** the score that maximises ring-level net value on validation (section 6). If no threshold beats zero, the rule is "flag nothing" and the report says so.

PR-AUC is average precision. It is compared with prevalence (the PR-AUC of a random ranking), which differs by split: 0.075, 0.107 and 0.177 percent for train, validation and test.

## 4. Rings (data stage D8)

Stage 02 showed that communities of the whole graph do not recover rings, so rings are extracted from the scored subgraph: flagged transfers become edges between accounts, connected components are found, components above `RS_COMMUNITY_CAP` accounts are split with the Stage 02 igraph Louvain code, and pieces with fewer than `RS_RING_MIN_SIZE` accounts are dropped. Transfers that cross a split between two pieces belong to no ring. `rings.json` [generated] lists the rings of `xgb_graph` at the net-value threshold on test, each with members, score and the five features that pushed its score most (XGBoost contributions).

## 5. Ring-level match

A predicted ring is a true positive when its account set has Jaccard similarity of at least `RS_RING_TAU` (default 0.5; 0.3 and 0.7 are also reported) with a ground-truth ring. Matching is one-to-one, greedy by descending Jaccard.

**Scope limit that must be quoted with every ring number:** ground truth exists only for the 370 pattern rings, which hold 3,209 of the 5,177 positive transfers. Ring recall says nothing about the other 1,968. A predicted ring that is real laundering but matches no pattern ring counts as a false positive under the strict match, so strict ring precision is pessimistic. The report therefore also gives `lenient_precision` (share of predicted rings containing at least one truly illicit flagged transfer) and, at transaction level, recall on ring positives and on unringed positives separately.

## 6. Cost model and the rupee assumptions

```
NV = capture x sum(INR amount of illicit flagged transfers in caught rings)
     - c_review x (rings flagged) - c_fp x (legitimate accounts inside flagged rings)
```

A flagged ring is "caught" if it holds at least one flagged transfer whose label is illicit. A legitimate account is one that appears in no illicit transfer of the evaluated split, counted once even if it sits in several rings. Labels are used here only to evaluate.

Defaults (agreed with the owner): `c_review` = INR 250 per ring, `c_fp` = INR 500 per legitimate account, `capture` = 1.0. They are planning assumptions, not measured or sourced figures.

Why these numbers:
- **INR 250 per review.** A reviewer opens a case, reads the subgraph and the evidence, and decides: assumed about 30 minutes. At a fully loaded analyst cost of roughly INR 500 per hour (an order-of-magnitude assumption for an Indian fraud-operations analyst, salary plus overhead over productive hours), 30 minutes is INR 250.
- **INR 500 per wrongly included account.** A legitimate customer inside a flagged ring means support contacts, delayed payments and some churn risk; INR 500 is about two review-equivalents, so a false positive costs more than the review that found it but is not made dominant. Because every action is human-gated, nothing is auto-blocked, which is why this is not set much higher.
- **Capture 1.0.** The plan defines loss as the amount a caught ring would have moved. That is the literal definition, so it is the headline.

Two honest warnings:
1. **Degenerate risk at capture 1.0.** INR amounts in this data can be very large and are synthetic, so with full volume as the gain, any ring with real volume can outweigh INR 250, and the rule drifts toward "flag everything that has a hit". The report therefore also re-chooses the threshold at capture 0.01 and 0.0001.
2. **Sensitivity sweep.** For every combination of review cost (100, 250, 1,000), false-positive cost (100, 500, 2,000, 5,000) and capture (1, 0.01, 0.0001), the threshold is re-chosen on validation and the test net value is reported (`cost_sweep` in `metrics.json` [generated]). Read conclusions off that table, not off the single default.

Amounts use the placeholder rates in `config/fx_rates_inr.json`; replace them or accept them before quoting rupee figures.

## 7. Ablations, robustness, latency

- **Ablation:** three variants with the same model class and rule: tabular only; graph features with hub control off (no degree cap, all edge weights 1, features rebuilt); graph features with hub control on. Hub control off versus on shows what the cap and IDF weights buy at detector level. The Stage 02 giant-component ablation is a separate, graph-level result.
- **Robustness:** a seeded share (0, 10, 20, 30, 50 percent) of transfers is removed from the test-window graph, features are rebuilt, and the fitted `xgb_graph` model and the validation thresholds are applied unchanged. Tabular columns are not perturbed. This is a robustness test only and is never used to tune anything or to design evasion.
- **Latency:** for each pattern ring with a flagged transfer, the number of events between the ring's first event and its earliest flagged transfer. It is a retrospective lower bound, because features are window-level; real streaming latency belongs to Stage 07.

## 8. Documented negative findings (real, from earlier stages)

- The 24-hour velocity rule scores at chance on validation (PR-AUC 0.00102 against prevalence 0.00107; Stage 01).
- Louvain communities do not recover rings: median best Jaccard about 0.04 (Stage 02). This is why rings are extracted from the scored subgraph.
- Hub control trims the giant component of the real transfer graph by only about 6 to 8 points; about 98 percent of validation ring accounts sit inside it (Stage 02).

Stage 03 findings (for example whether `xgb_graph` beats `xgb_tabular`, and how large flagged rings get) are NOT written yet because no real run exists. After the owner runs `scripts/reproduce.py`, add them here, including at least one result that went against the plan.

## 9. Other limitations

- Windows are retrospective: a transfer's features can use events later in the same window.
- Positive rate rises across the split, so test is a different mix from train.
- Unringed positives (38 percent) are invisible to ring metrics.
- Validation numbers are optimistic (early stopping and thresholds use validation).
- INR figures depend on placeholder FX rates and on planning-assumption costs.
- Only HI-Small has been run in the project; HI-Medium is untried.
- The velocity rule and tabular XGBoost here differ from the Stage 01 baselines (section 2).
