import pytest
from models.agent_run import AgentRun, Verification
from models.audit import AuditLog
from models.company import Company
from services.verification import extract_claimed_paths, extract_test_claims
from sqlmodel import select


def _make_company(session, name="Verification Test"):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company.id


def _payload(company_id, **overrides):
    payload = {
        "company_id": company_id,
        "external_ref": "github:careb36/le-fabrique#41",
        "producer": "copilot",
        "artifact": "diff contents",
        "claims": {"summary": "opened a PR"},
    }
    payload.update(overrides)
    return payload


def _ingest(test_client, monkeypatch, tmp_path, payload):
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    return test_client.post("/v1/agent_runs", json=payload)


def _verify(test_client, run_id, company_id, evidence=None):
    return test_client.post(
        f"/v1/agent_runs/{run_id}/verify",
        json={"company_id": company_id, "evidence": evidence},
    )


def test_empty_artifact_claiming_full_implementation_is_refuted(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    claims = {
        "body": (
            "Implements backend/app/crypto.py with Fernet encrypt/decrypt and "
            "16 tests in backend/tests/test_crypto.py; suite 59 -> 75 passed"
        )
    }
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact="", claims=claims),
    ).json()

    response = _verify(test_client, run["id"], company_id)

    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "refuted"
    artifact_check = next(c for c in body["checks"] if c["name"] == "artifact_nonempty")
    assert artifact_check["outcome"] == "refuted"
    assert "empty" in artifact_check["observation"]


def test_failed_ci_evidence_refutes_green_build_claim(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    artifact = "+++ b/backend/app/crypto.py\n+++ b/backend/tests/test_crypto.py\n"
    claims = {"summary": "backend/app/crypto.py added; build is green"}
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact=artifact, claims=claims),
    ).json()

    response = _verify(
        test_client,
        run["id"],
        company_id,
        {
            "ci": {
                "conclusion": "failure",
                "source": "github-check-run",
                "ref": "run/123",
            }
        },
    )

    assert response.json()["verdict"] == "refuted"
    test_check = next(
        c for c in response.json()["checks"] if c["name"] == "claimed_tests_evidenced"
    )
    assert test_check["outcome"] == "refuted"
    assert "failure" in test_check["observation"]


def test_test_claim_without_independent_evidence_is_unverifiable(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "75 tests passed"}),
    ).json()

    response = _verify(test_client, run["id"], company_id)

    assert response.json()["verdict"] == "unverifiable"
    assert response.json()["verdict"] not in {"verified", "refuted"}


@pytest.mark.parametrize(
    ("evidence", "outcome", "observation_text"),
    [
        (None, "unverifiable", "no CI evidence supplied"),
        ({}, "unverifiable", "no CI evidence supplied"),
        ({"ci": "success"}, "unverifiable", "no conclusion"),
        ({"ci": {}}, "unverifiable", "no conclusion"),
        ({"ci": {"conclusion": None}}, "unverifiable", "no conclusion"),
        (
            {
                "ci": {
                    "conclusion": "success",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "pass",
            "reports success (run/1)",
        ),
        (
            {
                "ci": {
                    "conclusion": "failure",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "refuted",
            "reports failure (run/1)",
        ),
        (
            {
                "ci": {
                    "conclusion": "timed_out",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "refuted",
            "reports timed_out (run/1)",
        ),
        (
            {
                "ci": {
                    "conclusion": "cancelled",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "unverifiable",
            "neither confirms nor refutes",
        ),
        (
            {
                "ci": {
                    "conclusion": "skipped",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "unverifiable",
            "neither confirms nor refutes",
        ),
        (
            {
                "ci": {
                    "conclusion": "neutral",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "unverifiable",
            "neither confirms nor refutes",
        ),
        (
            {
                "ci": {
                    "conclusion": "action_required",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "unverifiable",
            "neither confirms nor refutes",
        ),
        (
            {
                "ci": {
                    "conclusion": "stale",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "unverifiable",
            "neither confirms nor refutes",
        ),
        (
            {
                "ci": {
                    "conclusion": "new-conclusion",
                    "source": "github-check-run",
                    "ref": "run/1",
                }
            },
            "unverifiable",
            "neither confirms nor refutes",
        ),
    ],
)
def test_ci_evidence_conclusion_verdicts(
    evidence,
    outcome,
    observation_text,
    sqlite_session,
    test_client,
    monkeypatch,
    tmp_path,
):
    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "all tests pass"}),
    ).json()

    response = _verify(test_client, run["id"], company_id, evidence)

    check = next(
        c for c in response.json()["checks"] if c["name"] == "claimed_tests_evidenced"
    )
    assert check["outcome"] == outcome
    assert observation_text in check["observation"]
    assert "None" not in check["observation"]


def test_test_claim_with_successful_ci_and_present_paths_is_verified(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    artifact = "diff --git a/backend/app/crypto.py b/backend/app/crypto.py\n"
    claims = {"summary": "backend/app/crypto.py added; all tests pass"}
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact=artifact, claims=claims),
    ).json()

    response = _verify(
        test_client,
        run["id"],
        company_id,
        {
            "ci": {
                "conclusion": "success",
                "source": "github-check-run",
                "ref": "run/124",
            }
        },
    )

    assert response.json()["verdict"] == "verified"


def test_claimed_path_absent_from_artifact_is_refuted(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "Added backend/app/crypto.py"}),
    ).json()

    response = _verify(test_client, run["id"], company_id)

    assert response.json()["verdict"] == "refuted"
    file_check = next(
        c for c in response.json()["checks"] if c["name"] == "claimed_files_present"
    )
    assert file_check["outcome"] == "refuted"
    assert "backend/app/crypto.py" in file_check["observation"]


def test_claimed_path_in_new_file_diff_line_is_present(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    path = "backend/app/crypto.py"
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(
            company_id,
            artifact=f"+++ b/{path}\n",
            claims={"summary": f"Added {path}"},
        ),
    ).json()

    response = _verify(test_client, run["id"], company_id)

    assert response.json()["verdict"] == "verified"
    file_check = next(
        c for c in response.json()["checks"] if c["name"] == "claimed_files_present"
    )
    assert file_check["outcome"] == "pass"


def test_no_claims_and_no_artifact_is_verified(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, artifact="", claims=None),
    ).json()

    response = _verify(test_client, run["id"], company_id)

    assert response.json()["verdict"] == "verified"
    artifact_check = next(
        c for c in response.json()["checks"] if c["name"] == "artifact_nonempty"
    )
    assert artifact_check["observation"] == "no claims and no artifact"


def test_claimed_path_extraction_walks_nested_claims_and_ignores_urls():
    claims = {
        "body": [
            "Changed backend/app/crypto.py and README.md",
            {
                "more": "backend/app/crypto.py; see https://github.com/acme/repo/blob/main/backend/app/secret.py"
            },
        ],
        "bare": "crypto.py",
    }

    assert extract_claimed_paths(claims) == [
        "backend/app/crypto.py",
    ]


def test_test_claim_extraction_matches_claims_without_keyword_false_positives():
    claims = {
        "one": "75 passed",
        "nested": ["all tests pass", "CI is green", "passport.py and bypass"],
    }

    assert extract_test_claims(claims) == ["75 passed", "all tests pass", "CI is green"]


def test_reverification_appends_history_and_returns_oldest_first(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "75 tests passed"}),
    ).json()

    first_response = _verify(test_client, run["id"], company_id)
    first_id = first_response.json()["id"]
    first_before = sqlite_session.get(Verification, first_id)
    first_columns = {
        column.name: getattr(first_before, column.name)
        for column in Verification.__table__.columns
    }
    second_response = _verify(
        test_client,
        run["id"],
        company_id,
        {
            "ci": {
                "conclusion": "success",
                "source": "github-check-run",
                "ref": "run/125",
            }
        },
    )
    history_response = test_client.get(
        f"/v1/agent_runs/{run['id']}/verifications",
        params={"company_id": company_id},
    )
    verification_audits = [
        audit
        for audit in sqlite_session.exec(
            select(AuditLog).where(AuditLog.action == "agent_run_verified")
        ).all()
        if audit.details.get("company_id") == str(company_id)
    ]

    assert first_response.json()["verdict"] == "unverifiable"
    assert second_response.json()["verdict"] == "verified"
    assert len(verification_audits) == 2
    assert sqlite_session.get(Verification, second_response.json()["id"]).evidence == {
        "ci": {"conclusion": "success", "source": "github-check-run", "ref": "run/125"}
    }
    assert {
        column.name: getattr(sqlite_session.get(Verification, first_id), column.name)
        for column in Verification.__table__.columns
    } == first_columns
    assert [item["id"] for item in history_response.json()["verifications"]] == [
        first_id,
        second_response.json()["id"],
    ]


def test_verification_does_not_call_llm(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    import llm_proxy_client

    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "backend/app/crypto.py"}),
    ).json()

    def unexpected_llm_call(*args, **kwargs):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(llm_proxy_client.LLMProxyClient, "chat", unexpected_llm_call)
    monkeypatch.setattr(
        llm_proxy_client.LLMProxyClient, "chat_async", unexpected_llm_call
    )
    response = _verify(test_client, run["id"], company_id)

    assert response.status_code == 201


def test_verification_writes_one_linked_audit_and_updates_run_status(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_id, claims={"summary": "backend/app/crypto.py"}),
    ).json()

    response = _verify(test_client, run["id"], company_id)
    verification = sqlite_session.get(Verification, response.json()["id"])
    audits = [
        audit
        for audit in sqlite_session.exec(
            select(AuditLog).where(AuditLog.action == "agent_run_verified")
        ).all()
        if audit.details.get("company_id") == str(company_id)
    ]
    stored_run = sqlite_session.get(AgentRun, run["id"])
    assert response.status_code == 201
    assert len(audits) == 1
    assert audits[0].details["company_id"] == str(company_id)
    assert verification.audit_log_id == audits[0].id
    assert stored_run.status == response.json()["verdict"]


def test_cross_tenant_verification_returns_404_without_writes(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_a = _make_company(sqlite_session, name="Company A")
    company_b = _make_company(sqlite_session, name="Company B")
    run = _ingest(
        test_client,
        monkeypatch,
        tmp_path,
        _payload(company_b, claims={"summary": "work"}),
    ).json()

    response = _verify(test_client, run["id"], company_a)

    assert response.status_code == 404
    assert (
        sqlite_session.exec(
            select(Verification).where(Verification.agent_run_id == run["id"])
        ).all()
        == []
    )
    assert [
        audit
        for audit in sqlite_session.exec(
            select(AuditLog).where(AuditLog.action == "agent_run_verified")
        ).all()
        if audit.details.get("company_id") == str(company_a)
    ] == []
