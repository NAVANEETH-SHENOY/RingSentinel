# Architecture

Status at Stage 04: the data side (C1 to C3), the graph builder and feature extractor (C4, C5), the detectors, ring extractor and evaluation harness (C6 to C8), and the snapshot exporter, backend API and audit store (C10 to C12) are built. Stages 03 and 04 have been tested on synthetic or hand-made data only. The status column says what is built.

## Principles

- Deterministic core: detection, scoring and verification are ordinary code with fixed seeds.
- The language model is advisory: it writes explanations from structured facts, and every fact it cites is checked against the graph. It never changes a score or takes an action.
- Human gate: nothing is blocked automatically. Analysts confirm, dismiss or hold.
- Offline-first: the frontend works from snapshot JSON when the backend or the model provider is unavailable.
- Defense-only, mainstream dependencies, free tier.
- Variant-agnostic: all data paths derive from one setting (`RS_DATASET_VARIANT`), so HI-Small and HI-Medium run through identical code.

## Components (IDs from the plan)

| ID | Component | Responsibility | Status |
| --- | --- | --- | --- |
| C1 | Raw dataset store | Downloaded datasets (gitignored) plus a committed checksum manifest | Built: `data/raw/MANIFEST.json`, `backend/ringsentinel/ingest/manifest.py` |
| C2 | Ingestor | Normalize raw files to one event table | Built: `backend/ringsentinel/ingest/normalize.py` |
| C3 | Temporal splitter | Train, validation, test by time with no overlap | Built: `backend/ringsentinel/split.py` |
| C4 | Graph builder | Entity graph, hub pruning, IDF weights, communities | Built: `backend/ringsentinel/graph/build.py`, `backend/ringsentinel/graph/hubs.py`, `backend/ringsentinel/graph/communities.py`; derived noise layer `backend/ringsentinel/noise.py` |
| C5 | Feature extractor | Node and community features | Built: `backend/ringsentinel/features/node.py`, `backend/ringsentinel/features/community.py`, `backend/ringsentinel/features/build.py` |
| C6 | Detectors | Velocity rule, tabular XGBoost, graph-feature XGBoost, Isolation Forest | Built (Stage 03): `backend/ringsentinel/detect/tabular.py`, `backend/ringsentinel/detect/matrix.py`, `backend/ringsentinel/detect/models.py`, `backend/ringsentinel/detect/guard.py`; Stage 01 baselines remain in `backend/ringsentinel/models/baselines.py` |
| C7 | Ring extractor | Scores to candidate rings | Built: `backend/ringsentinel/rings/extract.py` |
| C8 | Evaluation harness | Metrics, cost model, ablations, robustness, latency | Built: `backend/ringsentinel/evaluate/metrics.py`, `backend/ringsentinel/evaluate/ringmatch.py`, `backend/ringsentinel/evaluate/cost.py`, `backend/ringsentinel/evaluate/report.py`, orchestration `backend/ringsentinel/stage03.py`; Stage 01 metrics remain in `backend/ringsentinel/evaluation/metrics.py` |
| C9 | AI layer | Investigator, verifier, devil's advocate | Stage 06 [planned] |
| C10 | Snapshot exporter | Static JSON bundle with version metadata | Built (Stage 04): `backend/ringsentinel/snapshots/export.py`, `backend/ringsentinel/snapshots/bundle.py`, `backend/ringsentinel/snapshots/schemas.py`, `scripts/export_snapshots.py` |
| C11 | Backend API | Serves snapshots, accepts analyst actions | Built (Stage 04): `backend/app/main.py`, `backend/app/routes.py`, `backend/app/ratelimit.py`, `backend/app/config.py`, `backend/app/schemas.py`, `backend/app/store.py` |
| C12 | Audit store | Append-only hash-chained log | Built (Stage 04): `backend/app/audit.py` (SQLite) |
| C13 | Drift monitor | Population stability index per window | Stage 07 [planned] |
| C14 | Replay engine | Time-ordered playback with latency | Stage 07 [planned] |
| C15 | Frontend | Queue, case view, metrics, audit, replay | Stage 05 and Stage 07; shell only: `frontend/package.json` |
| C16 | LLM provider | Groq (development), Gemini (production) | Stage 06 [planned] |
| Config | Settings and variant switch | Single source of configuration | Built: `backend/ringsentinel/config.py` |

## Architecture diagram

```mermaid
flowchart LR
  subgraph OFFLINE[Offline pipeline]
    C1[(C1 Raw datasets)] --> C2[C2 Ingestor]
    C2 --> C3[C3 Temporal splitter]
    C3 --> C4[C4 Graph builder]
    C4 --> C5[C5 Feature extractor]
    C5 --> C6[C6 Detectors]
    C6 --> C7[C7 Ring extractor]
    C6 --> C8[C8 Evaluation harness]
    C7 --> C8
    C7 --> C9[C9 AI layer]
    C6 --> C13[C13 Drift monitor]
    C2 --> C14[C14 Replay engine]
    C7 --> C14
    C8 --> C10[C10 Snapshot exporter]
    C9 --> C10
    C13 --> C10
    C14 --> C10
  end
  subgraph ONLINE[Online serving]
    C11[C11 FastAPI backend] <--> C12[(C12 Audit store)]
    C15[C15 Next.js frontend]
  end
  C16([C16 LLM provider]) <--> C9
  C10 --> C11
  C11 -->|ranked queue, cases, metrics| C15
  C10 -.->|static JSON fallback| C15
  C15 -->|analyst action| C11
```

Caption: the LLM explains evidence; it never changes a score or acts.

## Decisions fixed so far

- Candidate rings are built from real transfer edges, not from derived device or IP attributes. Hub control applies to transfer counterparties; derived attributes are label-blind noise used only to test robustness.
- Every detector outputs a transaction-level score; ring-level metrics use one shared ring extractor.
- Each time window uses a cumulative, past-only graph.
- Ring-level recall is measured against pattern-based rings only; transaction-level metrics use all labels.
- Labels come from the CSV `Is Laundering` column; ring truth comes from the patterns file and covers 3,209 of the 5,177 positives, so 1,968 positives belong to no known ring; see `docs/DATA.md`.
- Test rows are removed before any baseline feature is computed or model is fitted.
- Account identity is the account string alone (banks are not part of the node id).
- Windows are cumulative: val = train + val events, test = all events. Feature rows are the accounts active in the window's own split.
- The hub cap is tuned on the validation window only (smallest cap keeping 99 percent of validation ring accounts); `RS_HUB_CAP` overrides it.
- Hub control = IDF edge weight `1/log2(1+d)` on the larger endpoint degree plus a degree cap. It trims the giant component but does not break it; Louvain splits what remains (igraph implementation).
- Communities are context features, not ring candidates: on the real data they do not recover rings (Stage 02 negative finding). Ring extraction happens after scoring (D8, Stage 03).
- Stage 03: every detector scores each transfer; a transfer uses the graph features of its sender and receiver from the window of its own split. Train fits, validation chooses every threshold, test is scored once per detector (`SplitVault`). Rings come from the flagged transfers (components, then Louvain above the cap); ring match is Jaccard, one-to-one, on pattern rings only. The net-value cost model counts a ring as caught on any illicit hit and charges for legitimate accounts inside flagged rings. Defaults are planning assumptions (INR 250 per review, INR 500 per wrongly included account); see `docs/EVALUATION.md`.

- Stage 04: the bundle is six JSON files validated by JSON Schema and tied together by SHA-256 hashes; the API loads it into memory at start and refuses a bundle that fails any check. Drift, replay and the AI case file are exported as explicit placeholders until Stages 06 and 07. The queue is ranked by an expected-value heuristic that uses the uncalibrated model score. Analyst actions go to a hash-chained SQLite log with idempotency keys; a decided ring is closed.

## API (Stage 04)

All routes are under the prefix /api/v1. Read routes are open; the action route and the audit list need the X-Analyst-Token header.

```
GET  /health                      bundle id, git commit, counts, whether actions are enabled
GET  /queue?status=&limit=&offset=   ranked rings with status
GET  /cases/{ring_id}             one case: members, edges, top features, ai placeholder, status
GET  /metrics                     Stage 03 metrics, cost sweep, ablations, robustness, latency
GET  /drift                       placeholder until Stage 07
GET  /replay                      placeholder until Stage 07
POST /cases/{ring_id}/action      body: action, analyst, note, idempotency_key   (token)
GET  /audit?limit=&offset=        newest first                                    (token)
GET  /audit/verify                walks the hash chain
```

Status codes: 200 and 201 success (200 with replayed true for a repeated submission), 401 bad or missing token, 404 unknown ring, 409 key reuse for a different request or an action the ring's status does not allow, 422 invalid input, 429 rate limited (Retry-After header), 503 when no analyst token is configured. Request and response details, the audit log design and its limits: `docs/STAGE_04.md`.

The full decision log is in `docs/PROJECT_EXPLAINER.md`.
