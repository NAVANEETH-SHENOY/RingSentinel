r"""Ask the queue a question in plain words (constrained query, nothing is executed).

Usage (repo root, cmd):
  python scripts\ai_query.py "unverified rings with more than 10 members" --provider groq
  python scripts\ai_query.py --dsl "{\"filters\": []}"   (a ready JSON query, no model)

The model turns the question into a small JSON query; the program validates it (known fields and
operations only) and runs it in plain Python. `--dsl` skips the model entirely.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from ringsentinel.ai.provider import ProviderError, make_provider  # noqa: E402
from ringsentinel.ai.query import (  # noqa: E402
    QueryError,
    build_rows,
    parse_query,
    run_query,
    translate,
)
from ringsentinel.config import get_settings  # noqa: E402
from ringsentinel.snapshots.bundle import SnapshotError, load_bundle  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--dsl", default=None, help="a ready JSON query (no model is used)")
    parser.add_argument("--provider", choices=("fake", "groq", "gemini"), default=None)
    parser.add_argument("--snapshots", type=Path, default=None)
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        bundle = load_bundle(args.snapshots or settings.snapshots_dir)
        if args.dsl:
            query = parse_query(json.loads(args.dsl))
        elif args.question:
            provider = make_provider(
                args.provider or settings.llm_provider, model=settings.llm_model,
                timeout=settings.llm_timeout_s, min_interval_s=settings.llm_min_interval_s,
            )  # fmt: skip
            if provider is None:
                print("No provider configured. Use --provider, set RS_LLM_PROVIDER, or pass --dsl.")
                return 2
            query = translate(args.question, provider)
        else:
            parser.error("give a question or --dsl")
        rows = run_query(query, build_rows(bundle.queue["items"], bundle.cases["cases"]))
    except (QueryError, ProviderError, SnapshotError, json.JSONDecodeError) as exc:
        print(f"QUERY FAILED: {exc}")
        return 1
    print("query:", json.dumps(query.model_dump(mode="json"), sort_keys=True))
    print(f"{len(rows)} ring(s)")
    for r in rows:
        print(
            f"  #{r['rank']:<4} {r['ring_id']}  score {r['score']:.2f}  "
            f"members {r['n_members']:<5} value INR {r['expected_value_inr']:,.0f}  "
            f"ai {r['source']}/{r['verifier_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
