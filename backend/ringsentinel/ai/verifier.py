"""The verifier: every account, count, amount and date a case file cites is checked.

Two kinds of check run on every case file:

1. Structured claims. A finding lists the accounts it cites (`nodes`) and typed claims such as
   `out_degree of acct-3 is 4` or `edge_total_inr acct-1 -> acct-2 is 338392.79`. Each claim is
   recomputed from `CaseFacts`; a wrong value, an unknown account or a missing edge is an issue.
2. Prose scan. Every free-text field is scanned for account-like tokens, dates and numbers.
   An account that is not in the ring, a date that is not in the ring's edges, or a number that
   is not true of the ring is an issue. This is an existence check: it cannot tell that a true
   number was attached to the wrong thing, which is why numbers that matter belong in claims.

A case file is `verified` only when there are no issues. Warnings do not block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ringsentinel.ai.facts import DATE_RE, CaseFacts
from ringsentinel.ai.schemas import BenignCase, CaseFile, claim_groups, prose_fields

AMOUNT_ABS_TOL = 1.0  # rupees
AMOUNT_REL_TOL = 1e-9  # float noise only
PROSE_REL_TOL = 0.01  # prose amounts are often rounded
PERCENT_TOL = 0.6
MAX_ISSUES = 12

_UNITS = {
    "lakh": 1e5, "lakhs": 1e5, "crore": 1e7, "crores": 1e7, "thousand": 1e3, "k": 1e3,
    "million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "%": None, "percent": None,
}  # fmt: skip
_NUMBER_RE = re.compile(
    r"(?<![\w.-])(\d[\d,]*(?:\.\d+)?)\s*(lakhs?|crores?|thousand|million|billion|bn|k|m|%|percent)?"
    r"(?![\w-])",
    re.IGNORECASE,
)
# id-like words: at least one digit, at least six letters or digits, not a plain number
_ID_LIKE_RE = re.compile(
    r"(?<![\w-])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{6,}(?![\w-])"
)
_RING_ID_RE = re.compile(r"R-[0-9a-f]{12}")


@dataclass
class VerifyReport:
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(
        default_factory=lambda: {"nodes": 0, "counts": 0, "amounts": 0, "dates": 0, "numbers": 0}
    )

    @property
    def ok(self) -> bool:
        return not self.issues

    def add_issue(self, text: str) -> None:
        if len(self.issues) < MAX_ISSUES:
            self.issues.append(text)
        elif len(self.issues) == MAX_ISSUES:
            self.issues.append("(further issues omitted)")

    def as_dict(self, coverage: str, attempts: int) -> dict:
        return {
            "status": "verified" if self.ok else "unverified",
            "issues": list(self.issues), "warnings": list(self.warnings),
            "checked": dict(self.checked), "coverage": coverage, "attempts": attempts,
        }  # fmt: skip


def _close(claimed: float, true: float) -> bool:
    return abs(claimed - true) <= max(AMOUNT_ABS_TOL, AMOUNT_REL_TOL * abs(true))


def _check_claims(model: CaseFile | BenignCase, facts: CaseFacts, report: VerifyReport) -> None:
    for group, (nodes, counts, amounts) in enumerate(claim_groups(model), start=1):
        for token in nodes:
            report.checked["nodes"] += 1
            if facts.resolve(token) is None:
                report.add_issue(f"item {group}: account {token!r} is not in this ring")
        for claim in counts:
            report.checked["counts"] += 1
            true = facts.count_value(claim.metric, claim.account, claim.counterparty)
            where = _where(claim)
            if true is None:
                report.add_issue(f"item {group}: {claim.metric}{where} refers to something "
                                 "that is not in this ring's data")  # fmt: skip
            elif claim.value != true:
                report.add_issue(
                    f"item {group}: {claim.metric}{where} claimed {claim.value}, data says {true}"
                )
        for claim in amounts:
            report.checked["amounts"] += 1
            true = facts.amount_value(claim.metric, claim.account, claim.counterparty)
            where = _where(claim)
            if true is None:
                report.add_issue(f"item {group}: {claim.metric}{where} refers to something "
                                 "that is not in this ring's data")  # fmt: skip
            elif not _close(claim.value_inr, true):
                report.add_issue(
                    f"item {group}: {claim.metric}{where} claimed {claim.value_inr:,.2f}, "
                    f"data says {true:,.2f}"
                )  # fmt: skip


def _where(claim) -> str:
    parts = [p for p in (claim.account, claim.counterparty) if p]
    return f" [{' -> '.join(parts)}]" if parts else ""


def _unit_value(raw: str, unit: str | None) -> tuple[float, str]:
    value = float(raw.replace(",", ""))
    if unit is None:
        return value, ""
    unit = unit.lower()
    if unit in ("%", "percent"):
        return value, "%"
    return value * _UNITS[unit], "unit"  # type: ignore[operator]


def _number_supported(value: float, kind: str, known: list[float]) -> bool:
    if kind == "%":
        return any(abs(value - k) <= PERCENT_TOL for k in known)
    if kind == "" and float(value).is_integer() and abs(value) < 10000:
        return any(abs(value - k) < 1e-9 for k in known) or any(
            float(k).is_integer() is False and round(k) == value and abs(k) < 10000
            for k in known
        )  # fmt: skip
    return any(abs(value - k) <= max(AMOUNT_ABS_TOL, PROSE_REL_TOL * abs(k)) for k in known)


def _scan_prose(texts: list[str], facts: CaseFacts, report: VerifyReport) -> None:
    known = facts.known_numbers()
    known_dates = facts.known_dates()
    for text in texts:
        for alias in facts.alias_tokens(text):
            report.checked["nodes"] += 1
            if not facts.is_alias(alias):
                report.add_issue(f"text mentions account {alias!r}, which is not in this ring")
        scrub = text
        for alias in sorted(set(facts.alias_tokens(text)), key=len, reverse=True):
            scrub = scrub.replace(alias, " ")
        scrub = _RING_ID_RE.sub(" ", scrub)
        for match in DATE_RE.finditer(scrub):
            report.checked["dates"] += 1
            if match.group(1) not in known_dates:
                report.add_issue(f"text cites date {match.group(1)}, which is not in the data")
        scrub = DATE_RE.sub(" ", scrub)
        scrub = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?", " ", scrub)  # clock times: dates cover them
        for match in _ID_LIKE_RE.finditer(scrub):
            token = match.group(0)
            report.checked["nodes"] += 1
            if facts.resolve(token) is None:
                report.add_issue(f"text mentions {token!r}, which is not an account of this ring")
            scrub = scrub.replace(token, " ")
        for match in _NUMBER_RE.finditer(scrub):
            value, kind = _unit_value(match.group(1), match.group(2))
            if kind == "" and value in (0.0, 1.0):
                continue
            report.checked["numbers"] += 1
            if not _number_supported(value, kind, known):
                report.add_issue(f"text uses the number {match.group(0).strip()!r}, which is "
                                 "not a fact about this ring")  # fmt: skip


def verify(model: CaseFile | BenignCase, facts: CaseFacts) -> VerifyReport:
    """Check one parsed case file or benign case against the ring's own data."""
    report = VerifyReport()
    _check_claims(model, facts, report)
    if isinstance(model, CaseFile):
        for key in model.key_accounts:
            report.checked["nodes"] += 1
            if facts.resolve(key.account) is None:
                report.add_issue(f"key account {key.account!r} is not in this ring")
        shape = facts.structural_pattern()
        if model.pattern not in ("other", "unclear") and shape not in ("other", "unclear") \
                and model.pattern != shape:  # fmt: skip
            report.warnings.append(
                f"pattern {model.pattern!r} differs from the structural shape {shape!r}"
            )
    _scan_prose(prose_fields(model), facts, report)
    if facts.coverage != "full":
        report.warnings.append(
            f"edge data is {facts.coverage}: claims were checked against retained edges only"
        )
    return report
