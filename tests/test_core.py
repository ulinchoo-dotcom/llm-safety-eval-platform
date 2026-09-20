import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from safety_eval.metrics import cohen_kappa, coverage, summarize
from safety_eval.pipeline import DemoProvider, TokenBucket, make_graph
from safety_eval.schemas import CaseInput, ImportCases
from safety_eval.taxonomy import ATTACKS, CATEGORIES, SUBCATEGORIES


def example():
    return json.loads(Path("examples/benign-cases.json").read_text())["cases"][0]


def test_taxonomy_shape():
    assert len(CATEGORIES) == 5
    assert len(SUBCATEGORIES) == 23
    assert len(ATTACKS) == 8


@pytest.mark.parametrize(
    "change",
    [
        {"risk_category": "violence"},
        {"risk_subcategory": "unknown"},
        {"case_kind": "adversarial"},
        {"attack_type": "direct"},
        {"label_verified": True},
        {"severity": "P9"},
        {"expected_behavior": "refuse"},
        {"handbook_version": "future"},
        {"source": " "},
        {"prompt_payload": [{"role": "assistant", "content": "hello"}]},
        {"prompt_payload": [{"role": "user", "content": " "}]},
    ],
)
def test_case_validation(change):
    with pytest.raises(ValidationError):
        CaseInput(**(example() | change))


def test_multiturn():
    case = example()
    case["prompt_payload"] += [
        {"role": "assistant", "content": "背景"},
        {"role": "user", "content": "继续说明"},
    ]
    assert len(CaseInput(**case).prompt_payload) == 3


def test_duplicate_import():
    with pytest.raises(ValidationError):
        ImportCases(cases=[example(), example()])


def test_benign_does_not_fill_attack_coverage():
    result = coverage([example() | {"label_verified": True}])
    assert sum(sum(row.values()) for row in result["matrix"].values()) == 0
    assert result["meets_m2_coverage"] is False


def test_unverified_cases_do_not_meet_coverage():
    cases = [
        example() | {"case_kind": "adversarial", "risk_category": cat, "attack_type": attack}
        for cat in CATEGORIES
        for attack in ATTACKS
        for _ in range(10)
    ]
    assert coverage(cases)["meets_m2_coverage"] is False
    assert (
        coverage([case | {"label_verified": True} for case in cases])["meets_m2_coverage"] is True
    )


def test_kappa_degenerate_and_agreement():
    assert cohen_kappa([], [])["kappa"] is None
    assert cohen_kappa(["a"], ["a"])["kappa"] is None
    assert cohen_kappa(["a", "b"], ["a", "b"])["kappa"] == 1
    assert cohen_kappa(["a", "b"], ["b", "a"])["kappa"] == -1
    with pytest.raises(ValueError):
        cohen_kappa(["a"], [])


def test_unresolved_excluded_and_denominators():
    results = [
        example() | {"status": "pending_review", "passed": None},
        example() | {"status": "call_error", "passed": None},
        example() | {"status": "reviewed", "passed": False, "refused": True},
    ]
    stats = summarize(results)
    assert stats["total"] == 3 and stats["decided"] == 1
    assert stats["asr"]["value"] is None
    assert stats["overrefusal"]["value"] == 1
    assert stats["pass_rate"]["denominator"] == 1
    assert stats["release_eligible"] is False


async def test_graph_does_not_invent_judge():
    graph = make_graph(DemoProvider("demo-overrefusal"), TokenBucket(10000, 10))
    result = (await graph.ainvoke({"case": example()}))["result"]
    assert result["status"] == "pending_review"
    assert result["rule_signal"]["refusal_detected"] is True
    assert result["confidence"] is None and result["passed"] is None
    assert result["attempts"][0]["usage_source"] == "simulated"


async def test_call_failure_excluded_and_audited():
    class FailingProvider:
        model = "test"

        async def call(self, messages):
            raise ConnectionError("must not leak secrets from raw errors")

    result = (
        await make_graph(FailingProvider(), TokenBucket(10000, 10)).ainvoke({"case": example()})
    )["result"]
    assert result["status"] == "call_error"
    assert len(result["attempts"]) == 4
    assert result["attempts"][0]["cost"] is None
    assert "must not leak" not in json.dumps(result)
    assert "rule_signal" not in result


async def test_limiter_bounds():
    with pytest.raises(ValueError):
        TokenBucket(0, 1)
    limiter = TokenBucket(1000, 1)
    await asyncio.wait_for(asyncio.gather(*(limiter.acquire() for _ in range(5))), timeout=1)


def test_failed_expectation_is_not_necessarily_successful_attack():
    result = example() | {
        "case_kind": "adversarial",
        "expected_behavior": "refuse",
        "status": "reviewed",
        "passed": False,
        "refused": False,
        "attack_succeeded": False,
    }
    stats = summarize([result])
    assert stats["asr"]["value"] == 0
    assert stats["pass_rate"]["value"] == 0
