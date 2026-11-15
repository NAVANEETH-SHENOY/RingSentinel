# Deployment (Stage 09)

Free-tier topology. Nothing here has been run against the real hosts: the build environment cannot create accounts or reach them. What **was** run: the API in a clean virtual environment containing only `requirements-api.txt`, against a local Postgres 16, serving the real bundle, checked by `scripts/smoke_deployed.py` (44 checks passed, 0 failed, 1 warning: the bundle is not frozen yet). Everything that depends on the three hosts is marked **unverified** below and is covered by the smoke test you run after deploying.

```
browser --HTTPS--> Vercel (static site, frontend/out)         C15
   |                  |  reads /snapshots/*.json when the API is asleep or unreachable
   |--HTTPS--> Render free web service (FastAPI)              C11
                         |  serves data/snapshots (committed JSON bundle, D12)
                         |--TLS--> Neon free Postgres (audit table)   C12
```

| Piece | Host | Why this one | Limits to know (check each host's current pricing page; **unverified**, taken from public docs on 15 Nov 2026) |
| --- | --- | --- | --- |
| Frontend | Vercel Hobby | Static export, global CDN, free | Hobby is for non-commercial use. No server code runs here |
| API | Render free web service | Python, free, deploys from a Blueprint | Sleeps after about 15 minutes idle; about a minute to wake; 512 MB; the disk is erased on every restart and deploy |
| Audit log | Neon free Postgres | Free and not time-limited | Scales to zero when idle (the first query after a pause is slower); a monthly compute-hours allowance |

Render's own free Postgres is **not** used: it expires after 30 days. SQLite on Render's free disk is **not** used for the deployed audit log: the disk is ephemeral, so a restart would erase the analyst decisions and silently restart the hash chain.

## Before you deploy (one time, on your machine)

1. **Freeze the evaluation** (this is your decision, not the tool's): once you are happy with the numbers, run `python scripts\export_snapshots.py --frozen --git-commit <short sha>`. The numbers do not change; the bundle id does not change (it hashes the five data files only); `data/snapshots/meta.json` records `evaluation_frozen: true`. The smoke test warns until you do this.
2. `python scripts\sync_frontend_snapshots.py` copies the bundle to `frontend\public\snapshots` so the site works while the API sleeps.
3. Commit both folders: `data\snapshots` and `frontend\public\snapshots` (they are not ignored). `data\audit` and `.env` stay ignored.
4. `python scripts\secrets_scan.py` must report nothing. If you ever pasted a real key into a file or a chat, revoke it first (the Stage 08 note asks you to revoke the Groq key that was in a shared zip).

## 1. Neon (audit log)

1. Create a free account and a project; note the database name (the default is fine).
2. Copy the **direct** (non-pooled) connection string. It looks like `postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require`. Keep it secret: it contains the password. (The pooled string probably also works; only the direct one was reasoned about. **Unverified** on Neon.)
3. You do not create tables: the API creates `audit` and its index on first use (`CREATE TABLE IF NOT EXISTS`).

## 2. Render (API)

1. New > Blueprint > pick this repository. Render reads `render.yaml`: a free Python web service, build `pip install -r requirements-api.txt`, start `python -m uvicorn --factory app.main:create_app --app-dir backend --host 0.0.0.0 --port $PORT`, health check on the liveness route (GET /api/v1/live).
2. When asked, fill the three values marked `sync: false`:
   - `RS_AUDIT_DB_URL`: the Neon string from step 1.
   - `RS_ANALYST_TOKEN`: a long random string of at least 16 characters (for example 32 characters from a password manager). Analysts type it into the case page; share it only with people who may record decisions.
   - `RS_CORS_ORIGINS`: the exact Vercel address, such as `https://your-project.vercel.app` (no trailing slash, no wildcard). You get it in step 3; the first deploy can use a placeholder, then edit it and redeploy.
3. Wait for "Live". Open https://YOUR-SERVICE.onrender.com/api/v1/live in a browser: it must answer {"status":"ok"}.
4. `RS_TRUSTED_PROXY_HOPS=2` in `render.yaml` assumes Cloudflare and Render's proxy each append one address to `X-Forwarded-For`. Render's documentation does not state this; it is inferred from community reports (Render does not strip a client-supplied header, it appends to it, so entries to the left of the last two are client-controlled). **Unverified.** If it is wrong, rate limits apply per proxy address instead of per client, which can make one busy user throttle others; nothing else breaks. To check: send a request with a fake `X-Forwarded-For: 1.2.3.4` and look at the Render log line for the client address you see; change the value to 1 or 0 if the fake address shows up.
5. `PYTHON_VERSION=3.13.5` is set because Render needs a fully qualified version. The pins in `requirements-api.txt` were installed and run on Python 3.13 in the build environment; 3.11 and 3.12 are what CI uses.

## 3. Vercel (frontend)

1. Add New > Project > pick the repository. **Root Directory: `frontend`**. Framework: Next.js (detected). Build and output settings: leave the defaults (the project is a static export; `frontend/vercel.json` only adds security headers).
2. Environment variable (Production): `NEXT_PUBLIC_API_BASE_URL` = the Render address, no trailing slash. It is baked into the build, so changing it needs a redeploy. It is public by design: never put a token in any `NEXT_PUBLIC_*` variable.
3. Deploy. Copy the address into Render's `RS_CORS_ORIGINS` (step 2.2) and redeploy the API.
4. Custom domains: add the new origin to `RS_CORS_ORIGINS` as well (comma separated).

## 4. Smoke test (your machine, repo root, cmd)

```
python scripts\smoke_deployed.py --api https://<service>.onrender.com --web https://<project>.vercel.app --expect-postgres --expect-docs-off --wait 120
```

- `--wait 120` polls the liveness route (GET /api/v1/live) for up to two minutes, so a sleeping free-tier API is woken instead of failing the run.
- Add `--token <RS_ANALYST_TOKEN>` to also check the token-gated audit list; add `--write-check` to record **one real `hold` decision** on the lowest-ranked pending ring and prove a repeat is a safe replay. That entry is permanent in the hash chain; use the write check once, not on every run, or skip it.
- The script never prints the token. It prints PASS, FAIL, WARN or SKIP per check and ends with `SMOKE: n passed, n failed, ...`; the exit code is 1 on any failure.
- Expected on a healthy deployment: no FAIL. A WARN for `evaluation_frozen` means step "Freeze the evaluation" has not been done.

## When it breaks

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Site shows "Showing the saved snapshot", actions disabled | API asleep, or CORS or API address wrong | Wait about a minute and reload; run the smoke test; check `NEXT_PUBLIC_API_BASE_URL` and `RS_CORS_ORIGINS` |
| Smoke: `CORS allows the frontend origin` FAIL | `RS_CORS_ORIGINS` does not equal the Vercel address character for character | Fix it in Render, redeploy |
| Smoke: `frontend build points at this API` FAIL | `NEXT_PUBLIC_API_BASE_URL` was set after the build | Set it and redeploy the frontend |
| Smoke: `frontend snapshot matches the API bundle` FAIL | Frontend and API were built from different bundles | `python scripts\sync_frontend_snapshots.py`, commit, push |
| Actions answer 503 with `Retry-After` | Neon is waking, or the URL or password is wrong | Retry in a few seconds; if it persists, re-copy the connection string |
| Actions answer 503 "no analyst token" | `RS_ANALYST_TOKEN` not set | Set it in Render |
| Every request is 429 for one user | Proxy hop count wrong | See step 2.4 |
| Render deploy fails on install | Python version or a pin | Read the build log; the pins are in `requirements-api.txt` |

## What is not built

No custom domain, no monitoring or alerting, no backups of the audit database (use Neon's own tools), no CI deployment pipeline (Render and Vercel deploy on push), no multi-instance load test (the Postgres log takes an advisory lock so two instances cannot fork the chain, tested against a local Postgres 16 only).
