"""The verifier rejects planted node ids, counts, amounts, dates and numbers."""

import copy

import pytest
from pydantic import ValidationError
from ringsentinel.ai.facts import CaseFacts
from ringsentinel.ai.schemas import BenignCase, CaseFile, CountClaim
from ringsentinel.ai.template import template_case_file
from ringsentinel.ai.verifier import verify
from s06_cases import (
    CHAIN,
    T1,
    S,
    fan_out_case,
    good_benign_json,
    good_case_file_json,
    make_case,
)


@pytest.fixture
def f():
    return CaseFacts(fan_out_case())


def check(obj, f, cls=CaseFile):
    return verify(cls.model_validate(obj), f)


def test_a_correct_case_file_verifies(f):
    report = check(good_case_file_json(f), f)
    assert report.ok and report.issues == []
    assert report.checked["counts"] == 1 and report.checked["amounts"] == 1


def test_a_correct_benign_case_verifies(f):
    assert check(good_benign_json(f), f, BenignCase).ok


def test_the_template_always_verifies_on_every_shape():
    for edges in (fan_out_case()["edges"], CHAIN):
        f = CaseFacts(make_case(edges))
        assert verify(template_case_file(f), f).ok
    for case in (
        make_case([], members=["x", "y", "z"], edges_available=False),
        fan_out_case(edges_truncated=True, members_truncated=True),
    ):
        f = CaseFacts(case)
        assert verify(template_case_file(f), f).ok


def test_planted_fake_node_id_in_nodes_is_rejected(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["nodes"] = ["acct-1", "acct-42"]
    report = check(obj, f)
    assert not report.ok and "acct-42" in report.issues[0]


def test_planted_fake_real_looking_account_is_rejected(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["nodes"] = ["8F9999999"]
    assert not check(obj, f).ok


def test_planted_fake_key_account_is_rejected(f):
    obj = good_case_file_json(f)
    obj["key_accounts"][0]["account"] = "acct-77"
    assert any("key account" in i for i in check(obj, f).issues)


def test_a_real_member_id_is_accepted_where_an_alias_is(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["nodes"] = [S]
    obj["findings"][0]["counts"][0]["account"] = S
    assert check(obj, f).ok


def test_planted_fake_count_is_rejected_with_both_numbers(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["counts"][0]["value"] = 7
    report = check(obj, f)
    assert not report.ok
    assert "claimed 7" in report.issues[0] and "data says 4" in report.issues[0]


@pytest.mark.parametrize(
    ("metric", "value", "ok"),
    [("n_members", 5, True), ("n_members", 6, False), ("n_transfers", 10, True),
     ("n_transfers", 11, False), ("n_edges", 4, True), ("n_edges", 3, False)],
)  # fmt: skip
def test_global_counts(f, metric, value, ok):
    obj = good_case_file_json(f)
    obj["findings"][0]["counts"] = [{"metric": metric, "value": value}]
    obj["summary"] = "Ring."
    assert check(obj, f).ok is ok


def test_planted_fake_amount_is_rejected(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["amounts"][0]["value_inr"] = 338392.79 * 2
    report = check(obj, f)
    assert not report.ok and "edge_total_inr" in report.issues[0]


def test_amount_tolerance_is_one_rupee_not_more(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["amounts"][0]["value_inr"] = 338392.79 + 0.9
    assert check(obj, f).ok
    obj["findings"][0]["amounts"][0]["value_inr"] = 338392.79 + 1.5
    assert not check(obj, f).ok


def test_claim_about_a_missing_edge_is_rejected(f):
    obj = good_case_file_json(f)
    obj["findings"][0]["amounts"][0].update(account="acct-2", counterparty="acct-1")
    assert any("not in this ring's data" in i for i in check(obj, f).issues)


def test_claims_need_their_targets_at_parse_time():
    with pytest.raises(ValidationError):
        CountClaim(metric="out_degree", value=3)
    with pytest.raises(ValidationError):
        CountClaim(metric="edge_n_transfers", account="acct-1", value=3)
    with pytest.raises(ValidationError):
        CountClaim(metric="made_up_metric", value=3)


def test_unknown_fields_are_rejected_not_ignored(f):
    for extra in ({"score": 0.0}, {"action": "dismiss"}, {"rank": 1}):
        obj = good_case_file_json(f) | extra
        with pytest.raises(ValidationError):
            CaseFile.model_validate(obj)
    nested = good_case_file_json(f)
    nested["findings"][0]["new_score"] = 0.1
    with pytest.raises(ValidationError):
        CaseFile.model_validate(nested)


def test_prose_with_unknown_alias_is_rejected(f):
    obj = good_case_file_json(f)
    obj["summary"] = "acct-1 paid acct-9 at once."
    assert any("acct-9" in i for i in check(obj, f).issues)


def test_prose_with_unknown_id_like_token_is_rejected_known_one_passes(f):
    obj = good_case_file_json(f)
    obj["summary"] = "Look at 8F9999999 first."
    assert not check(obj, f).ok
    obj["summary"] = f"Look at {T1} first."
    assert check(obj, f).ok


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("There are 5 accounts and 10 transfers.", True),
        ("There are 7 accounts.", False),
        ("The ring moved INR 699,978.27 in total.", True),
        ("The ring moved INR 699,978.27", True),
        ("The ring moved about INR 7 lakh in total.", True),  # 700,000 is within 1 percent
        ("The ring moved INR 9,000,000.", False),
        ("The top receiver took 48.3% of the amount.", True),
        ("The top receiver took 80% of the amount.", False),
        ("One account made a single transfer, then 0 more.", True),
        ("It spans 67 hours.", True),
        ("It spans 500 hours.", False),
    ],
)
def test_numbers_in_prose(f, text, ok):
    obj = good_case_file_json(f)
    obj["summary"] = text
    assert check(obj, f).ok is ok, check(obj, f).issues


def test_dates_in_prose_must_exist_in_the_edges(f):
    obj = good_case_file_json(f)
    obj["summary"] = "Activity started on 2022-09-04 and ended 2022-09-06."
    assert check(obj, f).ok
    obj["summary"] = "Activity started on 2022-08-01."
    report = check(obj, f)
    assert not report.ok and "2022-08-01" in report.issues[0]


def test_ring_id_in_prose_is_not_flagged(f):
    obj = good_case_file_json(f)
    obj["summary"] = f"Ring {f.ring_id} looks like a fan-out."
    assert check(obj, f).ok


def test_pattern_mismatch_is_only_a_warning(f):
    obj = good_case_file_json(f)
    obj["pattern"] = "chain"
    report = check(obj, f)
    assert report.ok and any("differs from the structural shape" in w for w in report.warnings)


def test_partial_coverage_is_a_warning_and_is_reported():
    f = CaseFacts(fan_out_case(edges_truncated=True))
    report = check(good_case_file_json(f), f)
    assert report.ok and any("partial" in w for w in report.warnings)
    assert report.as_dict(f.coverage, 2) == {
        "status": "verified", "issues": [], "warnings": report.warnings,
        "checked": report.checked, "coverage": "partial", "attempts": 2,
    }  # fmt: skip


def test_issue_list_is_capped(f):
    obj = good_case_file_json(f)
    obj["summary"] = " ".join(f"acct-{n}" for n in range(50, 90))
    report = check(obj, f)
    assert len(report.issues) <= 13 and report.issues[-1] == "(further issues omitted)"


def test_verifier_does_not_modify_its_inputs(f):
    obj = good_case_file_json(f)
    before = copy.deepcopy(obj)
    check(obj, f)
    assert obj == before
