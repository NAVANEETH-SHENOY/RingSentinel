r"""Smoke test for a deployed RingSentinel (backend API and/or static frontend). Standard library
only.

    python scripts\smoke_deployed.py --api https://your-api.onrender.com --web https://your-app.vercel.app
    python scripts\smoke_deployed.py --api http://127.0.0.1:8000 --web http://127.0.0.1:3000

Options worth knowing:
  --wait 120          how long to keep trying while a free-tier backend wakes up (default 120 s)
  --expect-postgres   fail unless /health says the audit log is on Postgres (use for production)
  --expect-docs-off   fail if /api/docs answers (use for production, where RS_API_DOCS=0)
  --token T           analyst token: also checks the token-gated audit list. Never printed.
  --write-check       OPT-IN. Records ONE real "hold" on the lowest-ranked ring (and repeats the
                      request to prove the replay is safe). This adds a permanent audit entry and
                      changes that ring's status to held, so do not run it on the demo you will
                      record unless you accept that.

Exit code 0 = every check passed (warnings allowed), 1 = at least one failure.
What a pass means: the deployed pieces answer, agree on one snapshot bundle, and have the safety
settings on. It does not measure speed or load, and it cannot prove the analysis is right.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PAGES = ("/", "/case/", "/metrics/", "/audit/", "/drift/", "/replay/")
SNAPSHOT_FILES = (
    "queue.json",
    "cases.json",
    "metrics.json",
    "meta.json",
    "drift.json",
    "replay.json",
)
EVIL_ORIGIN = "https://evil.example.org"

Fetch = Callable[..., "tuple[int, dict[str, str], bytes]"]


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""


def http_fetch(
    method: str,
    url: str,
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: float = 30.0,
):
    """(status, lower-cased headers, body). HTTP error statuses are returned, not raised."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - scheme checked
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read()


def _json(raw: bytes) -> dict:
    """The body as a dict; {} when it is not JSON (a host's error page, say) or not an object."""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}
    return doc if isinstance(doc, dict) else {}


class Checker:
    def __init__(self, fetch: Fetch, *, clock=time.monotonic, sleep=time.sleep):
        self.fetch, self.results = fetch, []
        self._clock, self._sleep = clock, sleep

    def add(self, name: str, status: str, detail: str = "") -> bool:
        self.results.append(Result(name, status, detail))
        return status != FAIL

    def check(
        self, name: str, ok: bool, detail: str = "", *, warn_only: bool = False, hint: str = ""
    ) -> bool:
        """Record a check. `hint` (what to do next) is shown only when the check fails."""
        status = PASS if ok else (WARN if warn_only else FAIL)
        return self.add(name, status, detail if ok or not hint else f"{detail}; {hint}".strip("; "))

    def call(self, method: str, url: str, **kw):
        """One request. A network error becomes status 0 with the reason as the body, so a dead
        host is reported as failed checks and never as a traceback."""
        try:
            return self.fetch(method, url, **kw)
        except OSError as exc:
            return 0, {}, f"{type(exc).__name__}: {exc}".encode()

    def get(self, url: str, **kw):
        return self.call("GET", url, **kw)

    # ------------------------------------------------------------------ wake-up
    def wait_until_live(self, api: str, wait_s: float) -> bool:
        """Poll /live until it answers 200. A free-tier backend can take about a minute."""
        started, last = self._clock(), "no answer"
        while True:
            status, _, body = self.get(f"{api}/api/v1/live", timeout=15.0)
            last = f"HTTP {status}" if status else body.decode("utf-8", "replace")
            if status == 200:
                took = self._clock() - started
                self.add("api answers /live", PASS, f"after {took:.1f}s")
                if took > 20:
                    self.add("cold start", WARN, f"{took:.0f}s to wake: expected on a free tier")
                return True
            if self._clock() - started >= wait_s:
                self.add("api answers /live", FAIL, f"gave up after {wait_s:.0f}s ({last})")
                return False
            self._sleep(3.0)

    # ---------------------------------------------------------------------- API
    def check_api(
        self,
        api: str,
        *,
        web: str | None,
        token: str | None,
        expect_postgres: bool,
        expect_docs_off: bool,
        write_check: bool,
    ) -> dict:
        base = f"{api}/api/v1"
        facts: dict = {}
        status, headers, raw = self.get(f"{base}/health")
        if not self.check("GET /health is 200", status == 200, f"HTTP {status}"):
            return facts
        health = _json(raw)
        facts["bundle_id"] = health.get("bundle_id")
        self.check("health: status ok", health.get("status") == "ok", str(health.get("status")))
        self.check(
            "health: bundle_id is a sha256", bool(SHA256.match(str(health.get("bundle_id"))))
        )
        self.check(
            "health: rings exported",
            int(health.get("n_rings", 0)) > 0,
            f"n_rings={health.get('n_rings')}",
        )
        backend = health.get("audit_backend")
        if expect_postgres:
            self.check(
                "audit log is on Postgres", backend == "postgres", f"audit_backend={backend}"
            )
        else:
            self.add("audit backend", PASS, f"{backend} (not required to be postgres here)")
        if backend == "sqlite" and not expect_postgres:
            self.add(
                "audit persistence", WARN, "SQLite: on a free host the file is lost on restart"
            )
        self.check(
            "health: evaluation_frozen is true",
            health.get("evaluation_frozen") is True,
            f"evaluation_frozen={health.get('evaluation_frozen')}",
            warn_only=True,
            hint="export the release bundle with --frozen",
        )

        for name in ("x-content-type-options", "x-frame-options", "referrer-policy"):
            self.check(f"header {name}", name in headers, headers.get(name, "missing"))

        status, _, raw = self.get(f"{base}/queue?limit=5")
        items = _json(raw).get("items", []) if status == 200 else []
        self.check("GET /queue returns rings", status == 200 and len(items) > 0, f"HTTP {status}")
        ranks = [i["rank"] for i in items]
        self.check("queue is in rank order", ranks == sorted(ranks), str(ranks))
        if items:
            ring = items[0]["ring_id"]
            status, _, raw = self.get(f"{base}/cases/{ring}")
            case = _json(raw) if status == 200 else {}
            self.check("GET /cases/{ring} works", status == 200 and case.get("ring_id") == ring)
            self.check(
                "case carries an AI block with a verifier status",
                isinstance(case.get("ai"), dict) and "status" in case["ai"],
            )
        status, _, _ = self.get(f"{base}/cases/R-ffffffffffff")
        self.check("unknown ring is 404", status == 404, f"HTTP {status}")
        for name in ("metrics", "drift", "replay"):
            status, _, raw = self.get(f"{base}/{name}")
            body = _json(raw) if status == 200 else {}
            self.check(
                f"GET /{name}",
                status == 200 and body.get("bundle_id") == facts["bundle_id"],
                f"HTTP {status}",
            )
        status, _, raw = self.get(f"{base}/audit/verify")
        verify = _json(raw) if status == 200 else {}
        self.check(
            "audit chain verifies",
            status == 200 and verify.get("ok") is True,
            f"HTTP {status} {verify.get('reason')}",
        )

        docs_status, _, _ = self.get(f"{api}/api/docs")
        if expect_docs_off:
            self.check("interactive docs are off", docs_status == 404, f"HTTP {docs_status}")
        else:
            self.add(
                "interactive docs",
                PASS if docs_status in (200, 404) else WARN,
                f"HTTP {docs_status}",
            )

        if web:
            self._check_cors(base, web)
        self._check_auth(base, items, token, write_check)
        return facts

    def _check_cors(self, base: str, web: str) -> None:
        origin = web.rstrip("/")
        _, good, _ = self.get(f"{base}/live", headers={"Origin": origin})
        self.check(
            "CORS allows the frontend origin",
            good.get("access-control-allow-origin") == origin,
            f"allow-origin={good.get('access-control-allow-origin')!r}",
            hint="set RS_CORS_ORIGINS to the exact frontend URL",
        )
        _, bad, _ = self.get(f"{base}/live", headers={"Origin": EVIL_ORIGIN})
        self.check(
            "CORS refuses another origin",
            bad.get("access-control-allow-origin") is None,
            f"allow-origin={bad.get('access-control-allow-origin')!r}",
        )

    def _check_auth(self, base: str, items: list, token: str | None, write_check: bool) -> None:
        if not items:
            return
        ring = items[0]["ring_id"]
        body = json.dumps(
            {
                "action": "hold",
                "analyst": "smoke",
                "note": "",
                "idempotency_key": "smoke-no-token-0001",
            }
        ).encode()
        status, _, _ = self.call(
            "POST",
            f"{base}/cases/{ring}/action",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        if status == 503:
            self.add(
                "actions without a token",
                WARN,
                "503: the server has no RS_ANALYST_TOKEN (read-only)",
            )
        else:
            self.check("an action without the token is refused", status == 401, f"HTTP {status}")
        status, _, _ = self.get(f"{base}/audit")
        self.check(
            "audit list without the token is refused", status in (401, 503), f"HTTP {status}"
        )
        if token:
            status, _, raw = self.get(f"{base}/audit?limit=1", headers={"X-Analyst-Token": token})
            self.check("audit list with the token works", status == 200, f"HTTP {status}")
        else:
            self.add("token-gated audit list", SKIP, "no --token given")
        if write_check and token:
            self._write_check(base, token)
        elif write_check:
            self.add("write check", SKIP, "--write-check needs --token")

    def _write_check(self, base: str, token: str) -> None:
        status, _, raw = self.get(f"{base}/queue?limit=500&status=pending")
        pending = _json(raw).get("items", []) if status == 200 else []
        if not pending:
            self.add("write check", SKIP, "no pending ring left to hold")
            return
        ring = pending[-1]["ring_id"]
        key = f"smoke-{int(time.time())}-{ring[-6:]}"
        body = json.dumps(
            {
                "action": "hold",
                "analyst": "smoke-test",
                "note": "deployment smoke test",
                "idempotency_key": key,
            }
        ).encode()
        headers = {"Content-Type": "application/json", "X-Analyst-Token": token}
        first, _, raw1 = self.call(
            "POST", f"{base}/cases/{ring}/action", headers=headers, body=body
        )
        again, _, raw2 = self.call(
            "POST", f"{base}/cases/{ring}/action", headers=headers, body=body
        )
        self.check("write: first request is 201", first == 201, f"HTTP {first}")
        self.check(
            "write: repeat is a safe replay (200, replayed)",
            again == 200 and _json(raw2).get("replayed") is True,
            f"HTTP {again}",
        )
        status, _, raw = self.get(f"{base}/audit/verify")
        self.check("write: chain still verifies", status == 200 and _json(raw).get("ok") is True)

    # ----------------------------------------------------------------- frontend
    def check_web(self, web: str, *, api: str | None, api_bundle_id: str | None) -> None:
        web = web.rstrip("/")
        html = ""
        for page in PAGES:
            status, headers, raw = self.get(f"{web}{page}")
            ok = status == 200 and "text/html" in headers.get("content-type", "")
            self.check(f"page {page}", ok, f"HTTP {status}")
            if page == "/" and ok:
                html = raw.decode("utf-8", "replace")
        self.check("home page says RingSentinel", "RingSentinel" in html)
        served: dict[str, bytes] = {}
        for name in SNAPSHOT_FILES:
            status, _, raw = self.get(f"{web}/snapshots/{name}")
            doc = _json(raw) if status == 200 else None
            self.check(
                f"snapshot {name}",
                isinstance(doc, dict) and doc.get("schema_version") == "1",
                f"HTTP {status}",
            )
            served[name] = raw
        # meta.json records the sha256 of every other file; the bundle id is a hash of those.
        meta = _json(served.get("meta.json", b""))
        recorded = meta.get("files") if isinstance(meta.get("files"), dict) else {}
        bad = [
            n for n, h in recorded.items() if hashlib.sha256(served.get(n, b"")).hexdigest() != h
        ]
        self.check(
            "snapshot files match the hashes in meta.json",
            bool(recorded) and not bad,
            f"differ: {', '.join(sorted(bad))}" if bad else f"{len(recorded)} files",
            hint="mixed or edited bundle: re-run scripts\\export_snapshots.py then "
            "scripts\\sync_frontend_snapshots.py",
        )
        shown = meta.get("bundle_id")
        if api_bundle_id and shown:
            self.check(
                "frontend snapshot matches the API bundle",
                shown == api_bundle_id,
                f"frontend {str(shown)[:12]} vs API {api_bundle_id[:12]}",
                hint="run scripts\\sync_frontend_snapshots.py, commit, redeploy the frontend",
            )
        status, _, raw = self.get(f"{web}/demo-snapshots/queue.json")
        self.check("demo snapshot present (last-resort fallback)", status == 200)
        if api:
            self._check_baked_api(web, html, api)

    def _check_baked_api(self, web: str, html: str, api: str) -> None:
        """The API address is inlined at build time: look for it in the shipped scripts."""
        scripts = sorted(set(re.findall(r'(/_next/static/[^"\']+?\.js)', html)))[:40]
        for src in scripts:
            status, _, raw = self.get(f"{web}{src}")
            if status == 200 and api.rstrip("/").encode() in raw:
                self.add("frontend build points at this API", PASS, src)
                return
        self.add(
            "frontend build points at this API",
            FAIL if scripts else WARN,
            "API address not found in the shipped scripts: set NEXT_PUBLIC_API_BASE_URL "
            "in the host's build settings and redeploy"
            if scripts
            else "no scripts found",
        )


def summarize(results: list[Result]) -> tuple[int, int, int, int]:
    count = {s: sum(1 for r in results if r.status == s) for s in (PASS, FAIL, WARN, SKIP)}
    return count[PASS], count[FAIL], count[WARN], count[SKIP]


def main(argv: list[str] | None = None, *, fetch: Fetch = http_fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", help="backend base URL, e.g. https://x.onrender.com")
    parser.add_argument("--web", help="frontend base URL, e.g. https://x.vercel.app")
    parser.add_argument("--token", help="analyst token (also read from RS_ANALYST_TOKEN)")
    parser.add_argument("--wait", type=float, default=120.0)
    parser.add_argument("--expect-postgres", action="store_true")
    parser.add_argument("--expect-docs-off", action="store_true")
    parser.add_argument("--write-check", action="store_true")
    args = parser.parse_args(argv)
    if not args.api and not args.web:
        parser.error("give --api and/or --web")
    for url in (args.api, args.web):
        if url and not url.startswith(("http://", "https://")):
            parser.error(f"not an http(s) URL: {url}")
    import os

    token = args.token or os.environ.get("RS_ANALYST_TOKEN") or None
    checker = Checker(fetch)
    facts: dict = {}
    if args.api:
        api = args.api.rstrip("/")
        if checker.wait_until_live(api, args.wait):
            facts = checker.check_api(
                api,
                web=args.web,
                token=token,
                expect_postgres=args.expect_postgres,
                expect_docs_off=args.expect_docs_off,
                write_check=args.write_check,
            )
    if args.web:
        checker.check_web(args.web, api=args.api, api_bundle_id=facts.get("bundle_id"))
    for r in checker.results:
        print(f"{r.status:4}  {r.name}" + (f"  [{r.detail}]" if r.detail else ""))
    passed, failed, warned, skipped = summarize(checker.results)
    print(f"\nSMOKE: {passed} passed, {failed} failed, {warned} warnings, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
