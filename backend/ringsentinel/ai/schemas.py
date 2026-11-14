"""Typed output of the AI layer: the case file and the benign (devil's advocate) case.

Every model is strict (`extra="forbid"`): a reply that carries an unknown field, for example a
`score`, is rejected instead of ignored. Accounts are always written as aliases such as `acct-3`
while the model is talking; `facts.py` maps aliases back to real account ids afterwards.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROMPT_VERSION = "1"  # bump when prompts or the schemas below change; invalidates the cache
AI_BLOCK_STAGE = "06"

COUNT_METRICS = (
    "n_members", "n_transfers", "n_edges", "out_degree", "in_degree", "edge_n_transfers",
)  # fmt: skip
AMOUNT_METRICS = (
    "ring_total_inr", "account_out_inr", "account_in_inr", "edge_total_inr", "max_edge_inr",
)  # fmt: skip
NEEDS_ACCOUNT = {"out_degree", "in_degree", "account_out_inr", "account_in_inr"}
NEEDS_EDGE = {"edge_n_transfers", "edge_total_inr"}

Level = Literal["low", "medium", "high"]
Pattern = Literal[
    "fan_out", "fan_in", "chain", "cycle", "gather_scatter", "dense_cluster", "star", "other",
    "unclear",
]  # fmt: skip
Role = Literal["source", "sink", "relay", "hub", "member"]
BenignLabel = Literal[
    "shared_household_or_family", "shared_office_or_network", "payroll_or_recurring",
    "marketplace_or_settlement", "treasury_or_internal_sweep", "small_business_activity",
    "other",
]  # fmt: skip


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _ClaimBase(_Strict):
    account: str | None = Field(default=None, max_length=64)
    counterparty: str | None = Field(default=None, max_length=64)

    def _check_targets(self, metric: str) -> None:
        if metric in NEEDS_ACCOUNT and not self.account:
            raise ValueError(f"metric {metric} needs `account`")
        if metric in NEEDS_EDGE and not (self.account and self.counterparty):
            raise ValueError(f"metric {metric} needs `account` (sender) and `counterparty`")


class CountClaim(_ClaimBase):
    metric: Literal[COUNT_METRICS]  # type: ignore[valid-type]
    value: int

    @model_validator(mode="after")
    def _targets(self) -> CountClaim:
        self._check_targets(self.metric)
        return self


class AmountClaim(_ClaimBase):
    metric: Literal[AMOUNT_METRICS]  # type: ignore[valid-type]
    value_inr: float

    @model_validator(mode="after")
    def _targets(self) -> AmountClaim:
        self._check_targets(self.metric)
        return self


class Finding(_Strict):
    text: str = Field(min_length=1, max_length=400)
    nodes: list[str] = Field(default_factory=list, max_length=12)
    counts: list[CountClaim] = Field(default_factory=list, max_length=6)
    amounts: list[AmountClaim] = Field(default_factory=list, max_length=6)


class KeyAccount(_Strict):
    account: str = Field(max_length=64)
    role: Role
    reason: str = Field(min_length=1, max_length=200)


class CaseFile(_Strict):
    type: Literal["case_file"] = "case_file"
    pattern: Pattern
    suspicion: Level
    summary: str = Field(min_length=1, max_length=700)
    findings: list[Finding] = Field(min_length=1, max_length=6)
    key_accounts: list[KeyAccount] = Field(default_factory=list, max_length=6)
    limits: str = Field(default="", max_length=300)
    suggested_checks: list[str] = Field(default_factory=list, max_length=4)


class Hypothesis(_Strict):
    label: BenignLabel
    argument: str = Field(min_length=1, max_length=400)
    nodes: list[str] = Field(default_factory=list, max_length=12)
    counts: list[CountClaim] = Field(default_factory=list, max_length=6)
    amounts: list[AmountClaim] = Field(default_factory=list, max_length=6)
    strength: Level
    how_to_check: str = Field(default="", max_length=200)


class BenignCase(_Strict):
    type: Literal["benign_case"] = "benign_case"
    plausibility: Level
    summary: str = Field(min_length=1, max_length=500)
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)
    weakest_point: str = Field(default="", max_length=300)


def prose_fields(model: CaseFile | BenignCase) -> list[str]:
    """Every free-text string in a case file, for the verifier's prose scan."""
    out: list[str] = []
    if isinstance(model, CaseFile):
        out.append(model.summary)
        out.extend(f.text for f in model.findings)
        out.extend(k.reason for k in model.key_accounts)
        out.append(model.limits)
        out.extend(model.suggested_checks)
    else:
        out.append(model.summary)
        for h in model.hypotheses:
            out.extend([h.argument, h.how_to_check])
        out.append(model.weakest_point)
    return [t for t in out if t]


def claim_groups(model: CaseFile | BenignCase) -> list[tuple[list[str], list, list]]:
    """(nodes, count claims, amount claims) for each finding or hypothesis."""
    if isinstance(model, CaseFile):
        return [(f.nodes, f.counts, f.amounts) for f in model.findings]
    return [(h.nodes, h.counts, h.amounts) for h in model.hypotheses]
