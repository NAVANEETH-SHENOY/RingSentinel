"""Build the AI block (`cases.json` -> `ai`) for one ring or for a whole bundle.

Order of preference for one ring: the cache, then the language model (investigator, verifier,
devil's advocate), then the offline template. The block always says which one produced it, and
nothing here can touch a detector score: the only thing returned is the `ai` block.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ringsentinel.ai.cache import CaseCache, input_hash
from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.investigator import AgentResult, contested, devils_advocate, investigate
from ringsentinel.ai.provider import LLMProvider, ProviderError
from ringsentinel.ai.schemas import AI_BLOCK_STAGE, PROMPT_VERSION, BenignCase, CaseFile
from ringsentinel.ai.template import template_case_file
from ringsentinel.ai.verifier import verify

AI_DOC_SCHEMA_VERSION = "1"


@dataclass(frozen=True)
class AiOptions:
    max_tool_calls: int = 5
    verify_retries: int = 2
    advocate_tool_calls: int = 3
    advocate_retries: int = 1
    refresh: bool = False  # ignore cached entries unless the provider fails
    max_consecutive_failures: int = 3  # stop calling a provider that keeps failing


@dataclass
class Explained:
    block: dict[str, Any]
    provider_failed: bool = False


def _dealias(value: Any, facts: CaseFacts) -> Any:
    if isinstance(value, str):
        return facts.dealias_text(value)
    if isinstance(value, list):
        return [_dealias(v, facts) for v in value]
    if isinstance(value, dict):
        return {k: _dealias(v, facts) for k, v in value.items()}
    return value


def _shown(model: CaseFile | BenignCase, facts: CaseFacts) -> dict:
    """Model output as stored: real account ids instead of aliases, nulls dropped."""
    return _dealias(model.model_dump(mode="json", exclude_none=True), facts)


def _verifier_dict(report, facts: CaseFacts, attempts: int) -> dict:
    return report.as_dict(facts.coverage, attempts)


def _block(
    facts: CaseFacts, key: str, *, source: str, provider: LLMProvider | None,
    case_file: CaseFile, case_report, attempts: int, benign: BenignCase | None = None,
    benign_report=None, benign_attempts: int = 0,
    benign_failure_reason: str | None = None, trace: dict | None = None,
    fallback_kind: str | None = None, fallback_reason: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    is_contested, why = (False, None)
    if benign is not None and case_report.ok and benign_report is not None and benign_report.ok:
        is_contested, why = contested(case_file.suspicion, benign.plausibility)
    return {
        "status": "ready", "built_in_stage": AI_BLOCK_STAGE, "source": source,
        "input_hash": key, "prompt_version": PROMPT_VERSION,
        "provider": {"name": provider.name, "model": provider.model} if provider else None,
        "investigator": _shown(case_file, facts),
        "verifier": _verifier_dict(case_report, facts, attempts),
        "benign_explanation": _shown(benign, facts) if benign is not None else None,
        "benign_failure_reason": benign_failure_reason,
        "benign_verifier": _verifier_dict(benign_report, facts, benign_attempts)
        if benign_report is not None else None,
        "contested": is_contested, "contested_reason": why,
        "trace": trace or {"llm_calls": 0, "tool_calls": []},
        "fallback_kind": fallback_kind, "fallback_reason": fallback_reason,
    }  # fmt: skip


def _template_block(
    facts: CaseFacts, key: str, kind: str, reason: str
) -> dict[str, Any]:  # fmt: skip
    case_file = template_case_file(facts)
    report = verify(case_file, facts)  # must pass; the pipeline never skips the verifier
    return _block(
        facts, key, source="template", provider=None, case_file=case_file, case_report=report,
        attempts=1, fallback_kind=kind, fallback_reason=reason,
    )  # fmt: skip


def _attempts(result: AgentResult) -> int:
    """Final answers submitted: every failed one, plus the one that passed."""
    return max(1, result.verify_failures + (1 if result.verified else 0))


def _trace(*results: AgentResult) -> dict:
    return {
        "llm_calls": sum(r.llm_calls for r in results),
        "tool_calls": [
            {"tool": t.get("tool"), **({"error": t["error"]} if "error" in t else {})}
            for r in results for t in r.tool_calls
        ],
    }  # fmt: skip


def _from_cache(entry: dict, note: str | None = None) -> dict[str, Any]:
    block = dict(entry)
    block["source"] = "cache"
    if note:
        block["fallback_reason"] = note
    return block


def explain_case(
    case: dict, provider: LLMProvider | None, cache: CaseCache | None,
    options: AiOptions | None = None, *, offline_kind: str = "no_provider",
    offline_reason: str = "no provider configured; offline template used",
) -> Explained:  # fmt: skip
    """The `ai` block for one case. Never raises for provider trouble."""
    options = options or AiOptions()
    facts = CaseFacts(case)
    key = input_hash(facts)
    cached = cache.get(key) if cache is not None else None
    if cached is not None and not options.refresh:
        return Explained(_from_cache(cached))
    if provider is None:
        if cached is not None:
            return Explained(_from_cache(cached))
        return Explained(_template_block(facts, key, offline_kind, offline_reason))

    try:
        first = investigate(
            facts, provider, max_tool_calls=options.max_tool_calls,
            verify_retries=options.verify_retries,
        )  # fmt: skip
        if first.model is None:
            reason = first.note or "model produced no valid case file"
            return Explained(_template_block(facts, key, "no_valid_output", reason))
        benign_result: AgentResult[BenignCase] | None = None
        if first.verified:
            benign_result = devils_advocate(
                facts, provider, first.model, max_tool_calls=options.advocate_tool_calls,
                verify_retries=options.advocate_retries,
            )  # fmt: skip
    except ProviderError as exc:
        if cached is not None:
            return Explained(
                _from_cache(cached, f"provider failed ({exc}); cached entry served"), True
            )
        return Explained(
            _template_block(facts, key, "provider_error", f"provider error: {exc}"), True
        )

    results = [first] + ([benign_result] if benign_result is not None else [])
    block = _block(
        facts, key, source="llm", provider=provider, case_file=first.model,
        case_report=first.report, attempts=_attempts(first),
        benign=benign_result.model if benign_result else None,
        benign_report=benign_result.report if benign_result else None,
        benign_failure_reason=(
            benign_result.note
            if benign_result is not None and benign_result.model is None
            else None
),
        benign_attempts=_attempts(benign_result) if benign_result else 0,
        trace=_trace(*results),
    )  # fmt: skip
    everything_verified = first.verified and (benign_result is None or benign_result.verified)
    if cache is not None and everything_verified and benign_result is not None:
        cache.put(key, block)
    return Explained(block)


def build_ai_cases(
    cases: dict[str, dict], provider: LLMProvider | None, cache: CaseCache | None,
    options: AiOptions | None = None, *, limit: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[dict[str, dict], dict[str, Any]]:  # fmt: skip
    """AI blocks for every case, best rank first, plus an honest summary report."""
    options = options or AiOptions()
    ordered = sorted(cases.values(), key=lambda c: (c["rank"], c["ring_id"]))
    blocks: dict[str, dict] = {}
    failures = 0
    breaker_open = False
    used = 0
    for index, case in enumerate(ordered, start=1):
        active: LLMProvider | None = provider
        kind, reason = "no_provider", "no provider configured; offline template used"
        if provider is not None:
            if breaker_open:
                active, kind, reason = None, "provider_error", (
                    f"provider stopped after {options.max_consecutive_failures} failures in a row"
                )  # fmt: skip
            elif limit is not None and used >= limit:
                active, kind, reason = None, "outside_limit", (
                    "outside the LLM case limit; offline template used"
                )  # fmt: skip
        explained = explain_case(
            case, active, cache, options, offline_kind=kind, offline_reason=reason
        )
        if active is not None and explained.block["source"] != "cache":
            used += 1
        if active is not None:
            failures = failures + 1 if explained.provider_failed else 0
            breaker_open = failures >= options.max_consecutive_failures
        blocks[case["ring_id"]] = explained.block
        if progress:
            progress(index, len(ordered), case["ring_id"])
    return blocks, summarize(blocks, provider)


def summarize(blocks: dict[str, dict], provider: LLMProvider | None = None) -> dict[str, Any]:
    """Counts for the Stage 06 done-when: how many case files, how many verified, and why not."""
    source = Counter(b["source"] for b in blocks.values())
    kinds = Counter(b["fallback_kind"] for b in blocks.values() if b.get("fallback_kind"))
    llm_like = [b for b in blocks.values() if b["source"] in ("llm", "cache")]
    verified = sum(1 for b in llm_like if b["verifier"]["status"] == "verified")
    no_valid = kinds.get("no_valid_output", 0)
    attempted = len(llm_like) + no_valid
    benign = [b for b in llm_like if b.get("benign_verifier")]
    return {
        "n_cases": len(blocks), "prompt_version": PROMPT_VERSION,
        "provider": {"name": provider.name, "model": provider.model} if provider else None,
        "by_source": {k: source.get(k, 0) for k in ("llm", "cache", "template")},
        "template_reasons": dict(sorted(kinds.items())),
        "llm_attempted": attempted,
        "llm_verified": verified,
        "llm_unverified": len(llm_like) - verified,
        "llm_no_valid_output": no_valid,
        "verified_share_of_llm_attempted": round(verified / attempted, 4) if attempted else None,
        "benign_pass_verified": sum(
            1 for b in benign if b["benign_verifier"]["status"] == "verified"
        ),
        "benign_pass_unverified": sum(
            1 for b in benign if b["benign_verifier"]["status"] != "verified"
        ),
        "contested": sum(1 for b in llm_like if b.get("contested")),
        "note": (
            "Template case files are written by code and are not LLM output; they are excluded "
            "from the verified share. 'verified' means the verifier found no issue, not that "
            "the interpretation is correct."
        ),
    }  # fmt: skip


def ai_document(blocks: dict[str, dict]) -> dict[str, Any]:
    """The D10 file `ai_cases.json`."""
    return {
        "schema_version": AI_DOC_SCHEMA_VERSION, "prompt_version": PROMPT_VERSION,
        "cases": {rid: blocks[rid] for rid in sorted(blocks)},
    }  # fmt: skip
