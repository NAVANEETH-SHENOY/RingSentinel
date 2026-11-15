# Stage 07: human in the loop, feedback, drift and replay (M7, C13, C14, C15, D11)

Tag: v0.8.0 (after the owner runs the tests, the build and, ideally, the real-data export). Branch: `stage-07-hitl-drift-replay`.

This stage is built on the owner's merged Stage 06 repository (main at f42a7e2, with the owner's Groq provider changes and the owner's `AiCard`). Stage 05 (`docs/STAGE_05.md`) and Stage 06 (`docs/STAGE_06.md`) code is unchanged except where noted below.

## What was built

| Feature | Backend | Frontend |
| --- | --- | --- |
| Analyst decisions (confirm, dismiss, hold) | already in Stage 04 (`POST /cases/{ring_id}/action`) | `frontend/src/components/ActionPanel.tsx`, `source.act()` in `frontend/src/lib/source.ts`, `postJson` in `frontend/src/lib/http.ts`, `frontend/src/lib/idempotency.ts` |
| Bounded threshold feedback | `backend/ringsentinel/review/feedback.py`, `GET /feedback` | `frontend/src/components/FeedbackCard.tsx` |
| Live queue re-ranking | `GET /queue?order=live` (`annotate()`) | live columns and the order switch in `frontend/src/components/QueueView.tsx`, `frontend/src/lib/liveQueue.ts` |
| Drift with alerts | `backend/ringsentinel/monitor/drift.py`, `drift.json` [generated] | `frontend/src/components/DriftView.tsx`, `frontend/src/components/monitorCharts.tsx`, route `frontend/src/app/drift/page.tsx` |
| Replay with detection latency | `backend/ringsentinel/monitor/replay.py`, `replay.json` [generated] | `frontend/src/components/ReplayView.tsx`, `frontend/src/lib/replayView.ts` |
| AI panel | already built in the owner's Stage 06 (`AiCard` inside `frontend/src/components/CaseView.tsx`, test `frontend/tests/ai_card.test.tsx`) | unchanged in Stage 07 |

## The feedback rule

```
offset = clamp(step * (dismissed - confirm_weight * confirmed), 0, max_offset)         (log-odds)
effective threshold = sigmoid(logit(base threshold) + offset)
adjusted score      = sigmoid(logit(score) - offset)
adjusted value      = adjusted score x capture x amount - review cost - fp cost x accounts x (1 - adjusted score)
```

Defaults: step 0.1, max offset 1.5, confirm weight 1.0 (`RS_FEEDBACK_STEP`, `RS_FEEDBACK_MAX_OFFSET`, `RS_FEEDBACK_CONFIRM_WEIGHT`). Hard ceilings in code: 1.0, 3.0, 5.0. At the default maximum the odds threshold moves by a factor of e^1.5, about 4.5, no matter how many rings are dismissed.

- It is computed on read from the audit log (`statuses()` in `backend/app/audit.py`), so it is reproducible and reversible. Stored scores, the exported rank and the detectors are never changed.
- Only a rise is possible. Rings under the validated threshold are not in the bundle, so lowering it could not surface anything. Confirmations therefore only cancel dismissals.
- Held rings count for nothing. Decided rings are closed and listed last.
- **It is a heuristic and has not been validated.** `GET /feedback` says `validated: false` and the interface repeats it. Whether it improves precision is an open question; a later evaluation stage should test it.

## Drift (PSI)

`compute_drift()` cuts the validation scores into quantile bins (10 by default, ties merged), splits the test period into equal-width time windows (8 by default; integer edges, so no event moves between windows by rounding), and scores each window with

```
PSI = sum over bins of (test share - reference share) x ln(test share / reference share)       (shares floored at 1e-4)
```

Levels: below 0.10 ok, from 0.10 warn, from 0.25 alert (`RS_PSI_WARN_LEVEL`, `RS_PSI_ALERT_LEVEL`; rule of thumb, not a statistical test). A window with fewer than `RS_DRIFT_MIN_EVENTS` (500) events is "insufficient" and gets no PSI. Each window also reports mean score, flagged share, and precision and recall at the queue threshold (these use labels a live system would learn late).

**Deviation from the plan:** the plan compares with "the training distribution". Training scores were not kept (and would be in-sample), so the reference is the validation split. The `notes` field in `drift.json` [generated] says so.

## Replay

`compute_replay()` takes the transfers of every exported ring and records, per ring, when its flagged transfers first touch `RS_RING_MIN_SIZE` accounts (the detection time), the assembly time from its first transfer, and the number of test transfers in between. Where one true ring (the dataset's pattern id) supplies at least half of a ring's transfers, it also records the latency from that true ring's first transfer. The timeline holds three equal-length arrays (all test transfers, ring transfers, detections) over `RS_REPLAY_STEPS` steps.

**Limits:** replay is retrospective. Scores come from window-level features computed over the whole test window, so a live system could not have flagged these rings this early; latencies are a lower bound. Only exported rings are replayed. `partial` marks a ring whose exported transfers never reach the size limit.

## The interface

- Queue: with the API on, the order switch defaults to "Live (after analyst feedback)"; the feedback card shows the threshold, the counts and the limit notice; two columns show the adjusted value and the live order ("#n", "below threshold", "not worth a review", "decided"). From a snapshot nothing changes.
- Case: the decision panel needs the API and the token. Buttons follow the status rules (pending: three actions; held: confirm and dismiss; decided: none). A network failure keeps the same idempotency key so pressing the button again cannot record twice. The page reloads quietly after a decision.
- Explanation card: not changed in Stage 07; it is the owner's Stage 06 `AiCard` in `frontend/src/components/CaseView.tsx`. The demo bundle now carries rule-based template case files so the card is visible on the demo.
- Drift: status card (alert, drifting or stable), PSI bars with the warn and alert levels (the level is written on every non-ok bar), and a window table.
- Replay: slider and step buttons, the rings detected so far, a summary of assembly time and latency.

## Run it

```
python scripts\make_demo_bundle.py
python scripts\export_snapshots.py
python scripts\sync_frontend_snapshots.py
python scripts\run_api.py
cd frontend
npm ci
npm run check
npm run build
```

`export_snapshots.py` builds drift and replay when `scores.parquet` [generated] and `events.parquet` [generated] exist (`--no-monitor` skips them). The demo bundle's drift, replay and template case files are produced by the real code on invented inputs, and the interface marks the bundle as demo data.

## Tests

- `backend/tests/test_stage07_feedback.py`, `backend/tests/test_stage07_drift.py`, `backend/tests/test_stage07_replay.py`: the rule, PSI and replay arithmetic, including bounds, ties and determinism.
- `backend/tests/test_stage07_export.py`: the bundle with drift and replay.
- `backend/tests/test_stage07_api.py`: the live queue, `GET /feedback`, bounds through the API, and the scripted scenario (open the queue, open a case, act, retry, see the audit entry, verify the chain, replay, drift).
- `frontend/tests/stage07.test.tsx`: the decision panel, live queue, drift and replay pages, and the same scenario in the UI.

## Known limits

- Drift and replay have only run on the synthetic world and the demo bundle.
- The feedback rule is unvalidated; one shared token and free-text names.
- No live model call has ever been made (Stage 06).
- Everything else in `docs/PROJECT_EXPLAINER.md`, section 10.
