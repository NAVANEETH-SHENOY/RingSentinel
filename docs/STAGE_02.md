# Stage 02: noise layer, transfer graph with hub control, features

Tag: v0.3.0 (after the owner confirms the tests and the real-data run). Branch: `stage-02-graph-features`.

## What was built

- **D3 noise layer**: `backend/ringsentinel/noise.py`. Invents device, IP and VPA-handle attributes per account, purely to stress-test hub control. Synthetic, marked derived (`derived_` column prefix), built from account strings and the seed only, and never used as a feature. Output: `noise.parquet` [generated], `noise_report.json` [generated].
- **D5 graph**: `backend/ringsentinel/graph/build.py` aggregates a window's transfers into account-to-account edges (self-transfers are counted, not linked). `backend/ringsentinel/graph/hubs.py` holds the hub control: edge weight `1 / log2(1 + d)` with `d` the larger endpoint degree, and a degree cap above which an account is dropped. `backend/ringsentinel/graph/communities.py` takes connected components and splits those above the community cap with Louvain. Output: `pruning_report.json` [generated], `community_report.json` [generated].
- **Hub-cap tuning**: `run_tune()` in `backend/ringsentinel/stage02.py` picks the smallest cap (from 10, 15, 20, 30, 50, 100, 200, 500, 1000) that keeps at least 99 percent of the validation window's ring accounts. Validation labels set this one parameter; the test window is never used. Output: `hub_cap_tuning.json` [generated]. `RS_HUB_CAP` overrides it.
- **D6 features**: `backend/ringsentinel/features/node.py` (node features), `backend/ringsentinel/features/community.py` (community features), `backend/ringsentinel/features/build.py` (assembly per window). Output: `features.parquet` [generated].
- **Ablation**: `scripts/ablation_giant_component.py` (and `--step ablation` of `scripts/run_stage02.py`). Output: `ablation_giant_component.json` [generated].
- **Runner**: `scripts/run_stage02.py` (steps noise, tune, features, ablation).

## Windows and what "past-only" means here

Windows are cumulative: `train` = train events; `val` = train + val events; `test` = train + val + test events. A feature row exists for every account active in the window's own split and describes it using the whole cumulative window graph. So a feature never uses events after the window's end (tested by `test_validation_features_ignore_everything_after_the_boundary`). It can use events later in the same window: this is retrospective, window-level ring detection, not event-by-event streaming. Streaming and detection latency are Stage 07.

## Features (39 columns including window, account and community id)

Node: counts and INR amounts in and out, distinct counterparties in and out, raw degree, fan ratio `(out_deg+1)/(in_deg+1)`, flow ratio, reciprocal partners, active hours, first-to-last span, burstiness (share of the account's amount in its busiest hour), transfers per active hour, share of neighbours that are hubs, mean log-degree of neighbours, hub flag, and (controlled graph only) kept degree, IDF-weighted degree, triangles, directed 3-cycles, PageRank (scaled to mean 1).
Community (the account's community, controlled graph only): size, internal edges, density, mean and max weighted degree, PageRank mass, 3-cycles, max internal out- and in-degree and their ratio, busiest-hour share of internal amount, amount concentration (Herfindahl index of internal pair amounts), oversized flag.
Hub accounts have NaN in every controlled-graph column and community id -1. Labels, ring ids and splits are never read; this is guaranteed by passing only four columns in and tested.

## How to run (Windows cmd, repo root, venv active, Stage 01 outputs present)

```
pip install -r requirements.txt
python scripts\run_stage02.py
python scripts\ablation_giant_component.py
```

Steps: `--step noise|tune|features|ablation`, `--window train|val|test`. Expect a few minutes in total on the real HI-Small data (about a minute for the features step on the builder's machine).

## Real-data results (HI-Small, seed 42; builder's Linux run, owner's run pending)

Hub-cap tuning on the validation window chose cap 20: it drops 862 hub accounts and keeps 100 percent of validation ring accounts. Cap 15 would keep 97.7 percent and cap 10 only 91.6 percent.

Giant component of the transfer graph, as a share of all accounts in the window (about a fifth of accounts appear only in self-transfers and are isolated):

| Window | Transfer, no control | Transfer, hub control | Transfer + derived attributes, no control | Transfer + derived attributes, controlled |
| --- | --- | --- | --- | --- |
| train | 66.5 percent | 60.6 percent | 100.0 percent | 82.6 percent |
| val | 69.4 percent | 62.5 percent | 100.0 percent | 83.4 percent |
| test | 72.2 percent | 64.3 percent | 100.0 percent | 84.2 percent |

Reading it honestly: hub control removes the artificial total collapse caused by shared derived attributes (everything in one component becomes about 83 percent, with 52 attribute values dropped), but it only trims the giant component of the real transfer graph by only about 6 to 8 points. The giant component is a property of the transfer network itself (average degree near 3 is enough to connect most accounts), not of a few hubs. About 98 percent of validation ring accounts sit inside the giant component even after hub control.

Communities: connected components above 200 accounts are split with Louvain, giving about 150,000 to 160,000 communities per window, none left oversized, median size 1, 99th percentile about 60.

**Negative finding (documented on purpose).** Communities do not recover rings. For the 76 validation rings, the median best-community Jaccard is 0.036 and only 1.3 percent reach 0.5; for the 199 train rings, 2.0 percent reach 0.5. About half of the rings do have all their accounts inside one community, but that community is far larger than the ring. So plan section 5.3 as written (components and Louvain give candidate rings) does not produce usable ring candidates on this data. Community features are therefore context for the detector, and rings must be extracted from the flagged subgraph after scoring (data stage D8, Stage 03). The diagnostic is for reporting only; nothing was tuned on it.

Quick sanity check on the features (train window, ring account versus not, univariate AUC): degree 0.77, in-degree 0.73, PageRank 0.70, span 0.68, community size 0.67; triangles, cycles and reciprocity are near 0.5 (rings in this data are not triangle-rich). This is a sanity check that the columns carry information, not a result.

## Tests

`pytest` runs 132 tests after this stage (builder's run; see HANDOVER.md for the owner's). New ones cover: IDF weight values and monotonicity, hub cap boundary, cap selection, toy graph degrees, weights and known components with and without hub control, Louvain splitting and its oversized flag, noise determinism and independence (including a check that the independence test can detect dependence), hand-checked node features (cycles, triangles, burstiness, reciprocity), hub rows being NaN, features unchanged by label columns, features unchanged by post-boundary events, determinism, ablation on a toy graph, and the whole stage on the synthetic dataset.

## Known limits

- Window-level, not streaming (see above).
- The derived attributes are synthetic. Their small household and device groups (2 to 4 accounts) plus the transfer edges still link about 83 percent of accounts, which reflects how I designed the noise, not real IP behaviour.
- The hub cap was chosen with a rule that uses validation ring accounts; a different rule would give a different cap.
- Account identity is the account string only. 8 account strings appear under more than one bank in the data; they are merged.
- Louvain is igraph's multilevel implementation (see the decision log): networkx's version took over five minutes on the real giant component for some node orders.
- Features are float32. INR amounts rely on placeholder FX rates.
- The XGBoost baseline results from Stage 01 differ slightly across platforms; Stage 02 has no model.
