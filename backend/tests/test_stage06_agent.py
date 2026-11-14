"""The bounded tool loop: tool budget, retries, protocol errors, strict output, two passes."""

import json

import pytest
from ringsentinel.ai.investigator import contested, devils_advocate, investigate, parse_reply
from ringsentinel.ai.provider import ProviderError, ScriptedProvider
from s06_cases import facts, good_benign_json, good_case_file_json

F = facts()


def j(obj):
    return json.dumps(obj)


GOOD = j(good_case_file_json(F))
TOOL = j({"type": "tool_call", "tool": "edge_weights", "args": {"top_n": 2}})


def bad_count():
    obj = good_case_file_json(F)
    obj["findings"][0]["counts"][0]["value"] = 9
    return j(obj)


def test_tool_call_then_verified_answer():
    provider = ScriptedProvider([TOOL, GOOD])
    result = investigate(F, provider)
    assert result.verified and result.llm_calls == 2 and result.verify_failures == 0
    assert result.tool_calls == [{"tool": "edge_weights", "args": {"top_n": 2}}]
    system, messages = provider.calls[1]
    assert system.startswith("TASK: investigator")
    assert [m.role for m in messages] == ["user", "assistant", "user"]
    assert messages[-1].content.startswith("TOOL_RESULT edge_weights:")
    assert "acct-2" in messages[-1].content


def test_wrong_claim_gets_feedback_and_a_second_chance():
    provider = ScriptedProvider([bad_count(), GOOD])
    result = investigate(F, provider)
    assert result.verified and result.verify_failures == 1
    feedback = provider.calls[1][1][-1].content
    assert feedback.startswith("VERIFICATION_FAILED:") and "claimed 9" in feedback


def test_retries_are_bounded_and_the_case_is_marked_unverified():
    provider = ScriptedProvider([bad_count()] * 10)
    result = investigate(F, provider, verify_retries=2)
    assert result.model is not None and not result.verified
    assert result.report is not None and not result.report.ok
    assert result.verify_failures == 3 and result.llm_calls == 3 and len(provider.calls) == 3
    assert result.note == "verification failed after the allowed retries"


def test_zero_retries_means_one_attempt():
    provider = ScriptedProvider([bad_count()] * 5)
    result = investigate(F, provider, verify_retries=0)
    assert result.llm_calls == 1 and not result.verified


def test_tool_budget_is_enforced_in_code():
    calls = [TOOL] * 6 + [GOOD]
    provider = ScriptedProvider(calls)
    result = investigate(F, provider, max_tool_calls=2)
    assert result.verified
    real = [t for t in result.tool_calls if "rejected" not in t]
    assert len(real) == 2
    assert any(t.get("rejected") == "budget" for t in result.tool_calls)
    assert any("budget used up" in m.content for m in provider.calls[-1][1])


def test_a_model_that_only_calls_tools_cannot_loop_forever():
    provider = ScriptedProvider([TOOL] * 100)
    result = investigate(F, provider, max_tool_calls=2, verify_retries=1)
    assert result.model is None and result.note == "call budget exhausted"
    assert len(provider.calls) <= 2 + 1 + 2 + 2


def test_unknown_tool_and_bad_arguments_come_back_as_tool_errors():
    bad_tool = j({"type": "tool_call", "tool": "send_money", "args": {}})
    bad_args = j({"type": "tool_call", "tool": "edge_weights", "args": {"top_n": 999}})
    provider = ScriptedProvider([bad_tool, bad_args, GOOD])
    result = investigate(F, provider, max_tool_calls=3)
    assert result.verified
    assert [("error" in t) for t in result.tool_calls] == [True, True]
    assert provider.calls[1][1][-1].content.startswith("TOOL_ERROR send_money")


def test_malformed_replies_are_bounded():
    provider = ScriptedProvider(["no json at all"] * 10)
    result = investigate(F, provider)
    assert result.model is None and "valid JSON" in result.note
    assert len(provider.calls) == 3
    recovered = investigate(F, ScriptedProvider(["oops", "```json\n" + GOOD + "\n```"]))
    assert recovered.verified


def test_wrong_reply_type_is_a_protocol_error():
    provider = ScriptedProvider([j({"type": "benign_case"})] * 5)
    assert investigate(F, provider).model is None


def test_extra_fields_such_as_score_are_never_accepted():
    obj = good_case_file_json(F) | {"score": 0.0, "action": "dismiss"}
    provider = ScriptedProvider([j(obj)] * 5)
    result = investigate(F, provider, verify_retries=2)
    assert result.model is None  # strict schema: not even kept as a draft
    assert "score" in provider.calls[1][1][-1].content  # the model is told why


def test_provider_errors_propagate_to_the_caller():
    with pytest.raises(ProviderError):
        investigate(F, ScriptedProvider([ProviderError("down")]))


def test_parse_reply_tolerates_fences_and_chatter():
    assert parse_reply('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    for bad in ("", "[1, 2]", "{broken", "plain"):
        with pytest.raises(ValueError):  # JSONDecodeError is a ValueError
            parse_reply(bad)


def test_devils_advocate_uses_its_own_prompt_and_sees_the_first_pass():
    first = investigate(F, ScriptedProvider([GOOD])).model
    provider = ScriptedProvider([j(good_benign_json(F))])
    result = devils_advocate(F, provider, first)
    assert result.verified and result.model.plausibility == "medium"
    system, messages = provider.calls[0]
    assert system.startswith("TASK: devils_advocate")
    assert "FIRST_PASS_CASE_FILE" in messages[0].content and "fan_out" in messages[0].content


def test_devils_advocate_claims_are_verified_too():
    first = investigate(F, ScriptedProvider([GOOD])).model
    obj = good_benign_json(F)
    obj["hypotheses"][0]["counts"][0]["value"] = 12
    result = devils_advocate(F, ScriptedProvider([j(obj)] * 3), first, verify_retries=1)
    assert result.model is not None and not result.verified


@pytest.mark.parametrize(
    ("suspicion", "plausibility", "expected"),
    [
        ("high", "high", True), ("high", "medium", True), ("medium", "high", True),
        ("medium", "medium", False), ("high", "low", False), ("low", "high", False),
        ("low", "low", False),
    ],
)  # fmt: skip
def test_contested_flag(suspicion, plausibility, expected):
    flag, reason = contested(suspicion, plausibility)
    assert flag is expected and (reason is None) is (not expected)
