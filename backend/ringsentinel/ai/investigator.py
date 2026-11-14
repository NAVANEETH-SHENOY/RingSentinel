"""The investigator and the devil's advocate: one bounded tool loop, two prompts.

The loop is provider-neutral. Each reply must be one JSON object: a `tool_call` or the final
answer. The loop enforces, in code and not in the prompt:
  * a maximum number of tool calls,
  * a maximum number of malformed replies,
  * a maximum number of verification retries,
  * strict output models (unknown fields such as `score` are rejected),
  * the verifier on every final answer.
A provider failure (`ProviderError`) is not caught here; the caller decides on the fallback.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

from ringsentinel.ai import prompts
from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.provider import LLMProvider, Message
from ringsentinel.ai.schemas import BenignCase, CaseFile
from ringsentinel.ai.tools import ToolBox, ToolError
from ringsentinel.ai.verifier import VerifyReport, verify

M = TypeVar("M", bound=BaseModel)
MAX_PROTOCOL_ERRORS = 2


@dataclass
class AgentResult(Generic[M]):
    model: M | None = None  # last schema-valid final answer
    report: VerifyReport | None = None  # verifier report for `model`
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    verify_failures: int = 0
    note: str | None = None  # why there is no valid final answer, if there is none

    @property
    def verified(self) -> bool:
        return self.model is not None and self.report is not None and self.report.ok


def parse_reply(text: str) -> dict[str, Any]:
    """First JSON object in a reply (tolerates code fences and leading chatter)."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("reply is not a JSON object")
    return value


def _validation_issues(exc: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(p) for p in err['loc']) or 'reply'}: {err['msg']}"
        for err in exc.errors()[:8]
    ]


def run_agent(
    *, provider: LLMProvider, facts: CaseFacts, system: str, first_message: str,
    final_type: str, model_cls: type[M], max_tool_calls: int, verify_retries: int,
    max_tokens: int = 1500,
) -> AgentResult[M]:  # fmt: skip
    toolbox = ToolBox(facts)
    messages = [Message("user", first_message)]
    result: AgentResult[M] = AgentResult()
    protocol_errors = 0
    hard_cap = max_tool_calls + verify_retries + MAX_PROTOCOL_ERRORS + 2

    while result.llm_calls < hard_cap:
        text = provider.generate(system, messages, json_mode=True, max_tokens=max_tokens)
        result.llm_calls += 1
        messages.append(Message("assistant", text))
        try:
            obj = parse_reply(text)
        except (ValueError, json.JSONDecodeError):
            protocol_errors += 1
            if protocol_errors > MAX_PROTOCOL_ERRORS:
                result.note = "model kept replying without valid JSON"
                return result
            messages.append(Message("user", "TOOL_ERROR reply:\n" + json.dumps(
                {"error": "reply must be exactly one JSON object"})))  # fmt: skip
            continue

        kind = obj.get("type")
        if kind == "tool_call":
            if len(result.tool_calls) >= max_tool_calls:
                messages.append(
                    Message(
                        "user",
                        prompts.tool_error_message(
                            str(obj.get("tool")), "tool budget used up; give your final answer now"
                        ),
                    )
                )
                result.tool_calls.append({"tool": str(obj.get("tool")), "rejected": "budget"})
                continue
            name = str(obj.get("tool"))
            entry: dict[str, Any] = {"tool": name, "args": obj.get("args") or {}}
            try:
                output = toolbox.call(name, obj.get("args"))
                messages.append(Message("user", prompts.tool_result_message(name, output)))
            except ToolError as exc:
                entry["error"] = str(exc)
                messages.append(Message("user", prompts.tool_error_message(name, str(exc))))
            result.tool_calls.append(entry)
            continue

        if kind != final_type:
            protocol_errors += 1
            if protocol_errors > MAX_PROTOCOL_ERRORS:
                result.note = f"model never produced a {final_type}"
                return result
            messages.append(Message("user", prompts.tool_error_message(
                "reply", f"`type` must be tool_call or {final_type}")))  # fmt: skip
            continue

        try:
            parsed = model_cls.model_validate(obj)
        except ValidationError as exc:
            issues = _validation_issues(exc)
        else:
            report = verify(parsed, facts)
            result.model, result.report = parsed, report
            if report.ok:
                return result
            issues = report.issues
        result.verify_failures += 1
        if result.verify_failures > verify_retries:
            result.note = "verification failed after the allowed retries"
            return result
        messages.append(Message("user", prompts.verification_failed_message(issues)))

    result.note = result.note or "call budget exhausted"
    return result


def investigate(
    facts: CaseFacts, provider: LLMProvider, *, max_tool_calls: int = 5, verify_retries: int = 2
) -> AgentResult[CaseFile]:  # fmt: skip
    return run_agent(
        provider=provider, facts=facts, system=prompts.INVESTIGATOR_SYSTEM,
        first_message=prompts.case_context(facts, max_tool_calls), final_type="case_file",
        model_cls=CaseFile, max_tool_calls=max_tool_calls, verify_retries=verify_retries,
    )  # fmt: skip


def devils_advocate(
    facts: CaseFacts, provider: LLMProvider, case_file: CaseFile, *, max_tool_calls: int = 3,
    verify_retries: int = 1,
) -> AgentResult[BenignCase]:  # fmt: skip
    return run_agent(
        provider=provider, facts=facts, system=prompts.ADVOCATE_SYSTEM,
        first_message=prompts.advocate_context(
            facts, max_tool_calls, case_file.model_dump(mode="json")
        ),
        final_type="benign_case", model_cls=BenignCase, max_tool_calls=max_tool_calls,
        verify_retries=verify_retries,
    )  # fmt: skip


LEVEL_RANK = {"low": 0, "medium": 1, "high": 2}


def contested(suspicion: str, plausibility: str) -> tuple[bool, str | None]:
    """The two passes disagree when a suspicious reading meets a plausible innocent one."""
    s, p = LEVEL_RANK[suspicion], LEVEL_RANK[plausibility]
    if s + p >= 3 and s >= 1 and p >= 1:
        return True, (
            f"first pass suspicion is {suspicion}; devil's advocate rates the innocent "
            f"explanation {plausibility}"
        )
    return False, None


# Convenience type for callers that pass a factory instead of a provider.
ProviderFactory = Callable[[], LLMProvider]
