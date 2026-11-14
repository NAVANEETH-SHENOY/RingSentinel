"""Cache, offline fallback, provider failure, limits, circuit breaker and the honest report."""

import copy
import json

import pytest
from ringsentinel.ai.cache import CaseCache, input_hash
from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.pipeline import AiOptions, build_ai_cases, explain_case, summarize
from ringsentinel.ai.provider import (
    FailingProvider,
    ProviderError,
    ResilientProvider,
    ScriptedProvider,
)
from s06_cases import fan_out_case, good_benign_json, good_case_file_json, make_case, make_edge


def j(obj):
    return json.dumps(obj)


def good_script(case=None, plausibility="low"):
    f = CaseFacts(case or fan_out_case())
    return [j(good_case_file_json(f)), j(good_benign_json(f, plausibility))]


@pytest.fixture
def cache(tmp_path):
    return CaseCache(tmp_path / "cache")


def test_offline_case_file_is_a_verified_template_with_a_reason():
    block = explain_case(fan_out_case(), None, None).block
    assert block["status"] == "ready" and block["source"] == "template"
    assert block["provider"] is None and block["benign_explanation"] is None
    assert block["verifier"]["status"] == "verified"
    assert block["fallback_kind"] == "no_provider" and "offline" in block["fallback_reason"]
    assert len(block["input_hash"]) == 64


def test_llm_block_has_both_passes_provenance_and_real_account_ids(cache):
    provider = ScriptedProvider(good_script())
    block = explain_case(fan_out_case(), provider, cache).block
    assert block["source"] == "llm" and block["provider"] == {
        "name": "scripted",
        "model": "scripted-1",
    }
    assert block["verifier"]["status"] == "verified"
    assert block["benign_verifier"]["status"] == "verified"
    assert block["investigator"]["findings"][0]["nodes"] == ["8A0000001"]  # de-aliased
    assert "8A0000001" in block["investigator"]["summary"] and "acct-" not in json.dumps(block)
    assert block["trace"]["llm_calls"] == 2
    assert block["contested"] is False and block["fallback_kind"] is None


def test_verified_llm_output_is_cached_and_served_without_the_provider(cache):
    case = fan_out_case()
    explain_case(case, ScriptedProvider(good_script()), cache)
    assert len(cache) == 1
    silent = ScriptedProvider([])  # any call would raise
    block = explain_case(case, silent, cache).block
    assert block["source"] == "cache" and silent.calls == []
    assert block["verifier"]["status"] == "verified"


def test_cache_serves_when_the_provider_fails(cache):
    case = fan_out_case()
    explain_case(case, ScriptedProvider(good_script()), cache)
    down = FailingProvider("HTTP 503", retryable=True)
    explained = explain_case(case, down, cache, AiOptions(refresh=True))
    assert explained.provider_failed and down.calls == 1
    assert explained.block["source"] == "cache"
    assert "cached entry served" in explained.block["fallback_reason"]
    assert explained.block["investigator"]["pattern"] == "fan_out"


def test_provider_failure_without_a_cache_falls_back_to_the_template(cache):
    explained = explain_case(fan_out_case(), FailingProvider("boom"), cache)
    assert explained.provider_failed and explained.block["source"] == "template"
    assert explained.block["fallback_kind"] == "provider_error"
    assert "boom" in explained.block["fallback_reason"]
    assert len(cache) == 0  # a template is never cached, so a later model run replaces it


def test_unverified_output_is_kept_but_never_cached(cache):
    obj = good_case_file_json(CaseFacts(fan_out_case()))
    obj["findings"][0]["counts"][0]["value"] = 9
    provider = ScriptedProvider([j(obj)] * 3)
    block = explain_case(fan_out_case(), provider, cache).block
    assert block["source"] == "llm" and block["verifier"]["status"] == "unverified"
    assert block["verifier"]["issues"] and block["verifier"]["attempts"] == 3
    assert block["benign_explanation"] is None  # second pass only runs on a verified first pass
    assert len(cache) == 0


def test_no_valid_output_becomes_a_template_with_that_reason(cache):
    block = explain_case(fan_out_case(), ScriptedProvider(["nonsense"] * 5), cache).block
    assert block["source"] == "template" and block["fallback_kind"] == "no_valid_output"

def test_failed_benign_pass_preserves_failure_reason(cache):
    f = CaseFacts(fan_out_case())
    provider = ScriptedProvider(
        [j(good_case_file_json(f)), "nonsense", "nonsense", "nonsense"]
    )

    block = explain_case(fan_out_case(), provider, cache).block

    assert block["source"] == "llm"
    assert block["verifier"]["status"] == "verified"
    assert block["benign_explanation"] is None
    assert block["benign_failure_reason"] == "model kept replying without valid JSON"

def test_unverified_benign_pass_is_flagged_and_not_cached(cache):
    f = CaseFacts(fan_out_case())
    benign = good_benign_json(f)
    benign["hypotheses"][0]["counts"][0]["value"] = 12
    provider = ScriptedProvider([j(good_case_file_json(f)), j(benign), j(benign)])
    block = explain_case(fan_out_case(), provider, cache).block
    assert block["verifier"]["status"] == "verified"
    assert block["benign_verifier"]["status"] == "unverified"
    assert block["contested"] is False and len(cache) == 0


def test_contested_when_passes_disagree(cache):
    f = CaseFacts(fan_out_case())
    script = [j(good_case_file_json(f)), j(good_benign_json(f, plausibility="high"))]
    block = explain_case(fan_out_case(), ScriptedProvider(script), cache).block
    assert block["contested"] is True and "innocent" in block["contested_reason"]


def test_cache_key_changes_with_anything_the_case_depends_on():
    base = input_hash(CaseFacts(fan_out_case()))
    assert base == input_hash(CaseFacts(fan_out_case()))
    changed = [
        fan_out_case(score=0.81),
        fan_out_case(ring_id="R-aaaaaaaaaaaa"),
        fan_out_case(edges_truncated=True),
        make_case([*fan_out_case()["edges"], make_edge("8A0000001", "8B0000009", 1, 5.0)]),
    ]
    assert len({input_hash(CaseFacts(c)) for c in changed} | {base}) == 5
    assert input_hash(CaseFacts(fan_out_case()), prompt_version="2") != base


def test_stale_case_is_not_served_from_the_cache(cache):
    explain_case(fan_out_case(), ScriptedProvider(good_script()), cache)
    other = fan_out_case(score=0.5)
    block = explain_case(other, None, cache).block
    assert block["source"] == "template"


def test_corrupt_cache_entry_is_a_miss(cache, tmp_path):
    key = input_hash(CaseFacts(fan_out_case()))
    cache.directory.mkdir(parents=True)
    (cache.directory / f"{key}.json").write_text("{ not json", encoding="utf-8")
    assert cache.get(key) is None
    (cache.directory / f"{key}.json").write_text(j({"input_hash": "0" * 64}), encoding="utf-8")
    assert cache.get(key) is None
    with pytest.raises(ValueError):
        cache.get("../../etc/passwd")


def test_pipeline_never_modifies_the_case_or_its_score(cache):
    case = fan_out_case()
    before = copy.deepcopy(case)
    block = explain_case(case, ScriptedProvider(good_script()), cache).block
    assert case == before
    assert "score" not in block and "rank" not in block and "expected_value_inr" not in block


def cases_of(n):
    out = {}
    for i in range(n):
        c = fan_out_case(ring_id=f"R-{i:012x}", rank=i + 1)
        out[c["ring_id"]] = c
    return out


def test_limit_sends_only_the_best_ranked_cases_to_the_model(cache):
    cases = cases_of(4)
    scripts = []
    for case in list(cases.values())[:2]:
        scripts += good_script(case)
    provider = ScriptedProvider(scripts)
    blocks, report = build_ai_cases(cases, provider, cache, limit=2)
    assert [blocks[r]["source"] for r in sorted(blocks)] == ["llm", "llm", "template", "template"]
    assert blocks["R-000000000002"]["fallback_kind"] == "outside_limit"
    assert report["by_source"] == {"llm": 2, "cache": 0, "template": 2}
    assert report["template_reasons"] == {"outside_limit": 2}


def test_cached_cases_do_not_use_up_the_limit(cache):
    cases = cases_of(3)
    first = list(cases.values())[0]
    explain_case(first, ScriptedProvider(good_script(first)), cache)
    second = list(cases.values())[1]
    provider = ScriptedProvider(good_script(second))
    blocks, report = build_ai_cases(cases, provider, cache, limit=1)
    assert report["by_source"] == {"llm": 1, "cache": 1, "template": 1}


def test_circuit_breaker_stops_calling_a_provider_that_keeps_failing(cache):
    cases = cases_of(8)
    down = FailingProvider("quota exhausted")
    blocks, report = build_ai_cases(cases, down, cache, AiOptions(max_consecutive_failures=3))
    assert down.calls == 3
    assert report["by_source"]["template"] == 8
    assert report["template_reasons"] == {"provider_error": 8}
    assert "stopped after 3 failures" in blocks["R-000000000007"]["fallback_reason"]


def test_a_success_resets_the_failure_streak(cache):
    cases = cases_of(4)
    flaky = ScriptedProvider(
        [ProviderError("x"), ProviderError("x"), *good_script(), ProviderError("x")]
    )
    # case 1 and 2 fail, case 3 succeeds (2 calls), case 4 fails: breaker (3) never opens
    blocks, report = build_ai_cases(cases, flaky, cache, AiOptions(max_consecutive_failures=3))
    assert report["by_source"] == {"llm": 1, "cache": 0, "template": 3}


def test_report_is_honest_about_what_was_verified(cache):
    f = CaseFacts(fan_out_case())
    bad = good_case_file_json(f)
    bad["findings"][0]["counts"][0]["value"] = 9
    cases = cases_of(4)
    ids = sorted(cases)
    scripts = (
        good_script(cases[ids[0]])  # verified
        + [j(bad)] * 3  # unverified (1 + 2 retries)
        + ["junk"] * 3  # no valid output -> template
    )
    provider = ScriptedProvider(scripts)
    blocks, report = build_ai_cases(cases, provider, cache, limit=3)
    assert report["llm_attempted"] == 3  # verified + unverified + no valid output
    assert (report["llm_verified"], report["llm_unverified"], report["llm_no_valid_output"]) == (
        1, 1, 1,
    )  # fmt: skip
    assert report["verified_share_of_llm_attempted"] == pytest.approx(1 / 3, abs=1e-4)
    assert report["by_source"]["template"] == 2  # the failed one plus the one outside the limit
    assert "excluded" in report["note"]


def test_summary_of_an_all_template_run_has_no_share():
    blocks, report = build_ai_cases(cases_of(3), None, None)
    assert report["verified_share_of_llm_attempted"] is None and report["llm_attempted"] == 0
    assert report["by_source"]["template"] == 3 and report["provider"] is None
    assert summarize({})["n_cases"] == 0


def test_resilient_provider_paces_and_retries_only_retryable_errors():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    inner = ScriptedProvider(["ok1", ProviderError("429", retryable=True, retry_after=7), "ok2"])
    wrapped = ResilientProvider(
        inner, min_interval_s=2.0, max_attempts=3, base_backoff_s=1.0, sleep=sleep,
        clock=lambda: now[0],
    )  # fmt: skip
    assert wrapped.generate("s", []) == "ok1"
    assert wrapped.generate("s", []) == "ok2"  # first try 429 -> waits retry_after, then succeeds
    assert 7 in sleeps and wrapped.calls == 3
    assert any(0 < s <= 2.0 for s in sleeps)  # pacing between the first two calls

    hard = ResilientProvider(
        ScriptedProvider([ProviderError("401")]), sleep=sleep, clock=lambda: now[0]
    )
    with pytest.raises(ProviderError):
        hard.generate("s", [])
    assert hard.calls == 1  # not retryable: one attempt only

    always = ResilientProvider(
        FailingProvider("HTTP 429", retryable=True), max_attempts=3, base_backoff_s=0.0,
        min_interval_s=0.0, sleep=sleep, clock=lambda: now[0],
    )  # fmt: skip
    with pytest.raises(ProviderError):
        always.generate("s", [])
    assert always.inner.calls == 3
