# Stage 05: frontend core

Tag: v0.6.0 (after the owner runs `npm run check` and `npm run build`). Branch: `stage-05-frontend-core`.

## What was built

A light-mode Next.js app in `frontend/` that works entirely from the snapshot bundle and uses the Stage 04 API when it answers. It is a static export (`output: "export"`), so `npm run build` writes plain files to `frontend/out` [generated] and no Node server is needed to serve it.

| Page | File | Reads |
| --- | --- | --- |
| Review queue (`/`) | `frontend/src/components/QueueView.tsx` | queue |
| Case view (`/case/?id=R-...`) | `frontend/src/components/CaseView.tsx`, `frontend/src/components/ForceGraph.tsx` | one case |
| Metrics (/metrics/) | `frontend/src/components/MetricsView.tsx`, `frontend/src/components/charts.tsx` | metrics |
| Audit log (/audit/) | `frontend/src/components/AuditView.tsx` | API only |
| Replay (/replay/) | `frontend/src/components/ReplayView.tsx` | drift and replay placeholders |

Routes live in `frontend/src/app/`. The case page uses a query string, not a dynamic route, because a static export cannot know the ring ids in advance and the bundle can change without a rebuild.

## Where data comes from

`createSource` in `frontend/src/lib/source.ts` tries, in order: the API (only if `NEXT_PUBLIC_API_BASE_URL` is set; 4 second timeout), the real snapshot in `frontend/public/snapshots` [generated], then the built-in demo bundle in `frontend/public/demo-snapshots`. Every result carries its origin and, after a fallback, the reason. The header shows a chip (Live API, Snapshot, Demo data) and every page that fell back says so. A schema_version other than "1" is refused with a clear message. A 404 from a live API (unknown ring) is treated as an answer, not an outage.

Offline limits, by design: snapshots hold no analyst decisions, so the queue shows "not tracked" and the status filter is disabled; the audit page needs the backend (its chain check is public, the list needs the analyst token).

## The graph and the 500-node cap

`capGraph` in `frontend/src/lib/graph.ts` keeps the 500 accounts with the largest total transfer volume (sum of `total_inr` over incident edges), ties broken by account id, and keeps only edges whose ends both survive. The rule depends only on the case content, so the same case always shows the same graph. `layoutGraph` runs a d3-force layout to completion synchronously from d3's fixed starting arrangement (no randomness, no animation), then fits the view to the drawing. The page says how many accounts and links are shown out of how many, and whether the bundle itself was truncated.

**Gap against the plan:** the plan says "flagged ring plus its strongest neighbours". The Stage 04 bundle holds only the ring's own members and edges, so no neighbours exist to draw. Adding them needs an exporter change (schema version 2); it is not done here (see HANDOVER).

## The demo bundle

`scripts/make_demo_bundle.py` writes `frontend/public/demo-snapshots` (14 invented rings, one with 640 accounts to exercise the cap, and invented metrics). It uses the real schemas, hashing and loader, so it is a valid bundle. Everything in it is marked DEMO and the app shows a banner on every page. It exists so the interface can be built, tested and shown before Stage 03 has real results; it is not a result.

## Using the real bundle

```
python scripts\export_snapshots.py
python scripts\sync_frontend_snapshots.py
```

`scripts/sync_frontend_snapshots.py` loads the bundle with the API's checks, refuses a bad one, and copies the six files to `frontend/public/snapshots` [generated]. That folder is git-ignored by `frontend/.gitignore`; commit it only once the Stage 03 numbers are frozen. If the banner says "Snapshot out of date", the saved snapshot differs from what the live API serves; run the sync again.

cases.json holds every ring with up to 500 members and 500 edges; the browser downloads it whole for offline case pages. The sync script warns above 5 MiB.

## The metrics page and its main uncertainty

Stage 03 has never run on real data, so the exact key names inside metrics.json are those documented in `docs/PROJECT_EXPLAINER.md` (D9), not observed. `frontend/src/lib/metricsView.ts` therefore reads them tolerantly: the comparison table is the Stage 03 markdown table (`results_table_md`) parsed as is; the PR curve, cost curve, ablation, robustness and latency panels each say "not in this bundle, or not a layout this version recognises" when their data is missing or shaped differently, and the raw JSON is at the bottom of the page. The demo metrics were written to the same assumed layout, so a green test on them proves the code matches the assumption, not that the assumption matches Stage 03. Send the first real metrics snapshot file back to settle this.

## Accessibility and style

Light mode only (a test fails if a dark-mode media query appears). Text pairs are tested for WCAG AA contrast (`frontend/tests/palette.test.ts`); the accent #3395FF is 3.05:1 on white, so it is used for fills and focus rings, and links use a darker blue. Chart series colours come from a validated categorical palette; the two lightest are below 3:1, so charts always carry a legend, end-of-line labels and a table view. Graph nodes are keyboard-focusable. Fonts: Inter if installed, else the system font (no font download). Palette values are approximate and inspired by a clean fintech look; no brand assets are used.

## How to run (Windows cmd, from `frontend`)

```
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000 . Without `frontend/.env.local` [generated] it runs in snapshot-only mode on the demo bundle. To use the API, start it (`python scripts\run_api.py`), then put `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` in `frontend/.env.local` [generated] and restart `npm run dev` (the value is read at build time). The API's default CORS origin is already http://localhost:3000.

Checks: `npm run check` (type check, lint, tests). Production files: `npm run build`, then `npm run start` to serve `frontend/out` [generated].

## Known limits

- Read-only: confirm, dismiss and hold buttons are Stage 07. The API already supports them.
- No neighbours in the graph (see above); no AI case file (Stage 06); replay and drift pages show the not-built state (Stage 07).
- Metrics layouts unverified against real output (see above).
- The case page downloads all of cases.json in offline mode.
- Tested in jsdom and in one headless Chrome run against a real API process on the demo bundle; not tested on other browsers, Windows, or deployed hosting.
- Large rings with many separate pieces draw small nodes; select a node or use the link table below the graph.
