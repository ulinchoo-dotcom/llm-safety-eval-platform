import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from safety_eval.app import create_app
from safety_eval.config import Settings

TOKEN = "test-only-local-token-at-least-24-characters"


@pytest.fixture
def client():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL for real PostgreSQL integration tests")
    app = create_app(Settings(database_url=url, api_token=TOKEN))
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {TOKEN}"
        yield client


def case():
    row = json.loads(Path("examples/benign-cases.json").read_text())["cases"][0]
    row["case_code"] = "test-" + uuid4().hex
    return row


def test_auth_and_taxonomy(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/taxonomy", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert len(client.get("/api/taxonomy").json()["subcategories"]) == 23


def test_atomic_import_and_immutable_verification(client):
    existing, new = case(), case()
    assert client.post("/api/cases/import", json={"cases": [existing]}).status_code == 201
    assert client.post("/api/cases/import", json={"cases": [new, existing]}).status_code == 409
    # The rollback is real: importing new alone still succeeds.
    assert client.post("/api/cases/import", json={"cases": [new]}).status_code == 201
    assert (
        client.post(
            "/api/cases/import", json={"cases": [case() | {"label_verified": True}]}
        ).status_code
        == 422
    )


def test_parent_constraints(client):
    row = case()
    row["parent_case_code"] = "missing-" + uuid4().hex
    assert client.post("/api/cases/import", json={"cases": [row]}).status_code == 422
    a, b = case(), case()
    a["parent_case_code"], b["parent_case_code"] = b["case_code"], a["case_code"]
    assert client.post("/api/cases/import", json={"cases": [a, b]}).status_code == 422
    b["parent_case_code"] = None
    assert client.post("/api/cases/import", json={"cases": [a, b]}).status_code == 201


def test_filter_validation(client):
    assert client.get("/api/cases?risk_category=unknown").status_code == 422
    assert client.get("/api/cases?limit=10000").status_code == 422
    assert client.get("/api/cases?offset=-1").status_code == 422


def test_complete_review_workflow(client):
    item = case()
    assert client.post("/api/cases/import", json={"cases": [item]}).status_code == 201
    start = client.post(
        "/api/runs/demo", json={"case_codes": [item["case_code"]], "model": "demo-overrefusal"}
    )
    assert start.status_code == 201
    run_id = start.json()["run_id"]
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["case_snapshot"][0]["case_code"] == item["case_code"]
    assert run["metrics"]["decided"] == 0
    result = run["results"][0]
    assert result["attempts"][0]["prompt_version"] == "demo-v1"
    assert result["id"] in [r["id"] for r in client.get("/api/reviews/pending").json()]
    verdict = {
        "reviewer_id": "local-tester",
        "passed": False,
        "refused": True,
        "attack_succeeded": False,
        "severity": "P3",
        "note": "正常请求被错误拒答，人工确认。",
    }
    assert client.post(f"/api/reviews/{result['id']}", json=verdict).status_code == 201
    assert client.post(f"/api/reviews/{result['id']}", json=verdict).status_code == 409
    reviewed = client.get(f"/api/runs/{run_id}").json()
    assert reviewed["status"] == "completed"
    assert reviewed["metrics"]["overrefusal"]["value"] == 1
    assert reviewed["metrics"]["release_eligible"] is False
    assert reviewed["results"][0]["judge_status"] == "uncalibrated"


def test_missing_run_cases(client):
    response = client.post("/api/runs/demo", json={"case_codes": ["missing-" + uuid4().hex]})
    assert response.status_code == 404
    assert client.get(f"/api/runs/{uuid4()}").status_code == 404
    assert client.get("/api/runs/not-a-uuid").status_code == 422


def test_attack_review_uses_explicit_success_flag(client):
    item = case() | {
        "case_kind": "adversarial",
        "attack_type": "direct",
        "expected_behavior": "refuse",
    }
    assert client.post("/api/cases/import", json={"cases": [item]}).status_code == 201
    start = client.post("/api/runs/demo", json={"case_codes": [item["case_code"]]})
    run_id = start.json()["run_id"]
    result_id = client.get(f"/api/runs/{run_id}").json()["results"][0]["id"]
    response = client.post(
        f"/api/reviews/{result_id}",
        json={
            "reviewer_id": "tester",
            "passed": False,
            "refused": False,
            "attack_succeeded": False,
            "severity": "P3",
            "note": "没有正确拒答，但未提供攻击者请求的信息。",
        },
    )
    assert response.status_code == 201
    metrics = client.get(f"/api/runs/{run_id}").json()["metrics"]
    assert metrics["asr"]["value"] == 0
    assert metrics["pass_rate"]["value"] == 0
