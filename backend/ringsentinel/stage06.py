"""Stage 06 orchestration: build the AI blocks (D10) and merge them into the snapshot bundle.

    load bundle -> make provider -> build_ai_cases() -> write ai_cases.json, ai_report.json
    -> merge_ai_into_bundle() (optional)

The provider is optional. With none, every case gets the offline template. Nothing here reads or
writes a detector score.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ringsentinel.ai.cache import CaseCache
from ringsentinel.ai.pipeline import AiOptions, ai_document, build_ai_cases
from ringsentinel.ai.provider import LLMProvider, make_provider
from ringsentinel.config import Settings
from ringsentinel.snapshots.ai_merge import merge_ai_into_bundle
from ringsentinel.snapshots.bundle import canonical_text, clean, load_bundle


def options_from(settings: Settings, refresh: bool = False) -> AiOptions:
    return AiOptions(
        max_tool_calls=settings.llm_max_tool_calls, verify_retries=settings.llm_verify_retries,
        refresh=refresh,
    )  # fmt: skip


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def run_ai(
    settings: Settings, *, provider_name: str | None = None, model: str | None = None,
    limit: int | None = -1, refresh: bool = False, apply: bool = True,
    snapshots_dir: Path | None = None, provider: LLMProvider | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """Run the AI layer over the current bundle. `limit=-1` means the settings default,
    `limit=None` means every case. Returns the report (also written to ai_report.json)."""
    directory = Path(snapshots_dir) if snapshots_dir else settings.snapshots_dir
    bundle = load_bundle(directory)
    if provider is None:
        provider = make_provider(
            provider_name or settings.llm_provider, model=model or settings.llm_model,
            timeout=settings.llm_timeout_s, min_interval_s=settings.llm_min_interval_s,
        )  # fmt: skip
    effective_limit = settings.ai_max_llm_cases if limit == -1 else limit
    cache = CaseCache(settings.ai_cache_dir)
    blocks, report = build_ai_cases(
        bundle.cases["cases"], provider, cache, options_from(settings, refresh),
        limit=effective_limit, progress=progress,
    )  # fmt: skip
    ai_doc = ai_document(blocks)
    write_text(settings.ai_cases_path, canonical_text(ai_doc))
    report["llm_case_limit"] = effective_limit
    report["bundle_id_before"] = bundle.bundle_id
    if apply:
        merged, counts = merge_ai_into_bundle(directory, ai_doc)
        report["merge"] = counts
        report["bundle_id_after"] = merged.bundle_id
    write_text(settings.ai_report_path, canonical_text(clean(report)))
    return report


def format_report(report: dict[str, Any]) -> str:
    share = report["verified_share_of_llm_attempted"]
    lines = [
        f"cases                      {report['n_cases']}",
        f"provider                   {report['provider'] or 'none (offline template)'}",
        f"case files by source       {report['by_source']}",
        f"model-written, attempted   {report['llm_attempted']}",
        f"  verified                 {report['llm_verified']}",
        f"  unverified               {report['llm_unverified']}",
        f"  no valid output          {report['llm_no_valid_output']}",
        "verified share             "
        + ("n/a (no model-written case files)" if share is None else f"{100 * share:.1f}%"),
        f"benign pass verified       {report['benign_pass_verified']}"
        f" (unverified {report['benign_pass_unverified']})",
        f"contested (two passes)     {report['contested']}",
        f"template reasons           {report['template_reasons']}",
    ]
    if "merge" in report:
        lines.append(f"merged into bundle         {report['merge']}")
        lines.append(f"bundle_id                  {report['bundle_id_after']}")
    return "\n".join(lines)


def read_report(settings: Settings) -> dict[str, Any] | None:
    path = settings.ai_report_path
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
