import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import crypto
import pytest
from cryptography.fernet import Fernet
from models.agent_run import AgentRun
from models.audit import AuditLog
from models.company import Company
from models.github import GitHubRepoBinding
from services import github_adapter
from services.github_adapter import (
    infer_producer,
    pr_to_agent_run_payload,
    verify_webhook_signature,
)
from sqlmodel import select

FIXTURES = Path(__file__).parent / "fixtures" / "github"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _make_company(session, name="GitHub adapter test"):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company.id


def _bind(client, company_id, rule="all"):
    return client.post(
        "/v1/integrations/github/bindings",
        json={
            "company_id": company_id,
            "owner": "careb36",
            "repo": f"le-fabrique-{company_id}",
            "webhook_secret": "test-webhook-secret",
            "inclusion_rule": rule,
        },
    )


def _install_backfill(monkeypatch, pr, commits, diff):
    monkeypatch.setattr(
        github_adapter,
        "fetch_pull_requests",
        lambda owner, repo, **kwargs: [pr],
    )
    monkeypatch.setattr(
        github_adapter,
        "fetch_pr_commits",
        lambda owner, repo, number, **kwargs: commits,
    )
    monkeypatch.setattr(
        github_adapter,
        "fetch_pr_diff",
        lambda owner, repo, number, **kwargs: diff,
    )


def _backfill(client, company_id, repo=None):
    return client.post(
        "/v1/integrations/github/backfill",
        json={
            "company_id": company_id,
            "owner": "careb36",
            "repo": repo or f"le-fabrique-{company_id}",
        },
    )


def _make_signature(secret, body):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _webhook(
    client,
    pr,
    secret="test-webhook-secret",
    event="pull_request",
    action="opened",
    repository="careb36/le-fabrique",
):
    body = json.dumps(
        {
            "action": action,
            "repository": {"full_name": repository},
            "pull_request": pr,
        },
        separators=(",", ":"),
    ).encode()
    return client.post(
        "/v1/integrations/github/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": _make_signature(secret, body),
            "X-GitHub-Event": event,
        },
    )


def _no_ingestion(session, company_id):
    assert (
        session.exec(select(AgentRun).where(AgentRun.company_id == company_id)).all()
        == []
    )
    company_audits = [
        audit
        for audit in session.exec(select(AuditLog)).all()
        if isinstance(audit.details, dict)
        and audit.details.get("company_id") == str(company_id)
    ]
    assert company_audits == []


def test_verify_webhook_signature_checks_raw_body_and_header():
    body = b'{"action":"opened"}'
    signature = _make_signature("right-secret", body)

    assert verify_webhook_signature("right-secret", body, signature)
    assert not verify_webhook_signature("wrong-secret", body, signature)
    assert not verify_webhook_signature("right-secret", body, None)
    assert not verify_webhook_signature(
        "right-secret", body, signature.removeprefix("sha256=")
    )


@pytest.mark.parametrize(
    ("login", "author_type", "messages", "expected"),
    [
        ("Copilot", "User", [], "copilot"),
        ("copilot-swe-agent[bot]", "Bot", [], "copilot"),
        (
            "contributor",
            "User",
            ["Change\n\nCo-Authored-By: Claude <claude@example.com>"],
            "claude-code",
        ),
        ("dependabot[bot]", "Bot", [], "bot:dependabot[bot]"),
        ("octocat", "User", [], "human:octocat"),
    ],
)
def test_infer_producer_records_login(login, author_type, messages, expected):
    producer, raw_author = infer_producer(login, author_type, messages)

    assert producer == expected
    assert raw_author == login


def test_pr_to_agent_run_payload_preserves_claims_and_commit_order():
    pr = _fixture("pr33.json")
    commits = _fixture("commits33.json")
    payload = pr_to_agent_run_payload(
        company_id=42,
        owner="careb36",
        repo="le-fabrique",
        pr=pr,
        commits=commits,
        diff_text=(FIXTURES / "pr33.diff").read_text(),
    )

    assert payload.external_ref == "github:careb36/le-fabrique#33"
    assert payload.claims["body"] == pr["body"]
    assert payload.claims["commit_messages"] == [
        commit["commit"]["message"] for commit in commits
    ]
    assert payload.model is None
    assert payload.subject["head_sha"] == pr["head"]["sha"]
    assert payload.subject["changed_files"] == [
        "frontend/package.json",
        "frontend/src/components/AnalyticsDashboard.test.tsx",
    ]


def test_fetch_pull_requests_paginates_and_filters_by_since(monkeypatch):
    next_url = "https://api.github.com/repos/acme/widgets/pulls?page=2"
    responses = [
        [
            {
                "number": 1,
                "created_at": "2025-01-01T00:00:00Z",
            }
        ],
        [
            {
                "number": 2,
                "created_at": "2025-02-01T00:00:00Z",
            }
        ],
    ]
    requests = []

    def fake_get(url, *, headers, params, timeout):
        requests.append((url, headers, params, timeout))
        index = len(requests) - 1
        response_headers = {"Link": f'<{next_url}>; rel="next"'} if index == 0 else {}
        return github_adapter.httpx.Response(
            200,
            json=responses[index],
            headers=response_headers,
            request=github_adapter.httpx.Request("GET", url),
        )

    monkeypatch.setattr(github_adapter.httpx, "get", fake_get)

    pulls = github_adapter.fetch_pull_requests(
        "acme",
        "widgets",
        token="token-value",
        since="2025-01-15T00:00:00Z",
    )

    assert [pr["number"] for pr in pulls] == [2]
    assert len(requests) == 2
    assert requests[0][1]["Authorization"].startswith("Bearer ")
    assert requests[0][1]["Authorization"].endswith("token-value")
    assert requests[0][2]["per_page"] == 100
    assert requests[1][2] is None


def test_fetch_pull_requests_raises_typed_rate_limit(monkeypatch):
    def fake_get(url, *, headers, params, timeout):
        return github_adapter.httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1790000000"},
            request=github_adapter.httpx.Request("GET", url),
        )

    monkeypatch.setattr(github_adapter.httpx, "get", fake_get)

    with pytest.raises(github_adapter.GitHubRateLimited) as error:
        github_adapter.fetch_pull_requests("acme", "widgets", token="token-value")

    assert error.value.reset_at == "1790000000"


def test_pr27_empty_diff_is_ingested_and_refuted(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _install_backfill(
        monkeypatch,
        _fixture("pr27.json"),
        _fixture("commits27.json"),
        (FIXTURES / "pr27.diff").read_text(),
    )

    assert _bind(test_client, company_id).status_code == 201
    backfill = _backfill(test_client, company_id)
    run = sqlite_session.exec(
        select(AgentRun).where(AgentRun.company_id == company_id)
    ).one()
    verification = test_client.post(
        f"/v1/agent_runs/{run.id}/verify",
        json={"company_id": company_id, "evidence": None},
    )

    assert backfill.json() == {"ingested": 1, "skipped": 0, "errors": []}
    assert run.artifact_size == 0
    assert verification.json()["verdict"] == "refuted"


def test_pr33_failed_ci_refutes_and_missing_evidence_is_unverifiable(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _install_backfill(
        monkeypatch,
        _fixture("pr33.json"),
        _fixture("commits33.json"),
        (FIXTURES / "pr33.diff").read_text(),
    )
    _bind(test_client, company_id)
    _backfill(test_client, company_id)
    run = sqlite_session.exec(
        select(AgentRun).where(AgentRun.company_id == company_id)
    ).one()

    failed = test_client.post(
        f"/v1/agent_runs/{run.id}/verify",
        json={
            "company_id": company_id,
            "evidence": {
                "ci": {
                    "conclusion": "failure",
                    "source": "github-check-run",
                    "ref": "run/34610513782",
                }
            },
        },
    )
    missing = test_client.post(
        f"/v1/agent_runs/{run.id}/verify",
        json={"company_id": company_id, "evidence": None},
    )

    assert failed.json()["verdict"] == "refuted"
    assert missing.json()["verdict"] == "unverifiable"


def test_valid_webhook_ingests_pull_request(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _bind(test_client, company_id)
    monkeypatch.setattr(github_adapter, "fetch_pr_commits", lambda *args, **kwargs: [])
    monkeypatch.setattr(github_adapter, "fetch_pr_diff", lambda *args, **kwargs: "diff")

    response = _webhook(
        test_client,
        _fixture("pr27.json"),
        repository=f"careb36/le-fabrique-{company_id}",
    )

    assert response.status_code == 202
    assert response.json()["created"] is True
    assert (
        len(
            sqlite_session.exec(
                select(AgentRun).where(AgentRun.company_id == company_id)
            ).all()
        )
        == 1
    )


def test_webhook_fetches_github_off_the_event_loop(
    test_client, sqlite_session, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _bind(test_client, company_id)
    monkeypatch.setattr(github_adapter, "fetch_pr_commits", lambda *args, **kwargs: [])
    loop_absent = []

    def fake_fetch_pr_diff(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_absent.append(True)
            return "diff"
        loop_absent.append(False)
        return "diff"

    monkeypatch.setattr(github_adapter, "fetch_pr_diff", fake_fetch_pr_diff)

    response = _webhook(
        test_client,
        _fixture("pr27.json"),
        repository=f"careb36/le-fabrique-{company_id}",
    )

    assert response.status_code == 202
    assert loop_absent == [True]


def test_invalid_webhook_signature_writes_nothing(sqlite_session, test_client):
    company_id = _make_company(sqlite_session)
    _bind(test_client, company_id)
    body = json.dumps({"repository": {"full_name": "careb36/le-fabrique"}}).encode()

    response = test_client.post(
        "/v1/integrations/github/webhook",
        content=body,
        headers={
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Event": "pull_request",
        },
    )

    assert response.status_code == 401
    _no_ingestion(sqlite_session, company_id)

    absent = test_client.post(
        "/v1/integrations/github/webhook",
        content=body,
        headers={"X-GitHub-Event": "pull_request"},
    )
    assert absent.status_code == 401
    _no_ingestion(sqlite_session, company_id)


def test_unbound_repository_webhook_writes_nothing(sqlite_session, test_client):
    company_id = _make_company(sqlite_session)
    response = _webhook(test_client, _fixture("pr27.json"))

    assert response.status_code == 401
    _no_ingestion(sqlite_session, company_id)


def test_synchronize_creates_new_version_and_identical_diff_is_noop(
    sqlite_session, test_client, monkeypatch, tmp_path
):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _bind(test_client, company_id)
    monkeypatch.setattr(github_adapter, "fetch_pr_commits", lambda *args, **kwargs: [])
    diff = {"value": "first"}
    monkeypatch.setattr(
        github_adapter, "fetch_pr_diff", lambda *args, **kwargs: diff["value"]
    )
    pr = _fixture("pr27.json")
    repository = f"careb36/le-fabrique-{company_id}"
    first = _webhook(test_client, pr, repository=repository)
    first_id = first.json()["agent_run_id"]
    first_run = sqlite_session.get(AgentRun, first_id)
    original_columns = {
        column.name: getattr(first_run, column.name)
        for column in AgentRun.__table__.columns
    }

    diff["value"] = "second"
    second = _webhook(test_client, pr, action="synchronize", repository=repository)
    third = _webhook(test_client, pr, action="synchronize", repository=repository)
    original = sqlite_session.get(AgentRun, first_id)
    updated_columns = {
        column.name: getattr(original, column.name)
        for column in AgentRun.__table__.columns
    }

    assert second.json()["version"] == 2
    assert second.json()["created"] is True
    assert third.json()["created"] is False
    assert original.artifact_text == "first"
    assert updated_columns == original_columns


def test_non_pull_request_event_is_ignored(sqlite_session, test_client):
    company_id = _make_company(sqlite_session)
    _bind(test_client, company_id)

    response = _webhook(
        test_client,
        _fixture("pr27.json"),
        event="push",
        repository=f"careb36/le-fabrique-{company_id}",
    )

    assert response.status_code == 204
    _no_ingestion(sqlite_session, company_id)


def test_backfill_is_idempotent(sqlite_session, test_client, monkeypatch, tmp_path):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _bind(test_client, company_id)
    _install_backfill(
        monkeypatch,
        _fixture("pr27.json"),
        _fixture("commits27.json"),
        (FIXTURES / "pr27.diff").read_text(),
    )

    first = _backfill(test_client, company_id)
    second = _backfill(test_client, company_id)

    assert first.json()["ingested"] == 1
    assert second.json() == {"ingested": 0, "skipped": 1, "errors": []}


@pytest.mark.parametrize(
    ("rule", "author", "expected_ingested"),
    [
        ("bots_only", {"login": "human", "type": "User"}, 0),
        ("non_bots", {"login": "Copilot", "type": "User"}, 0),
    ],
)
def test_inclusion_rule_filters_producers(
    sqlite_session, test_client, monkeypatch, tmp_path, rule, author, expected_ingested
):
    company_id = _make_company(sqlite_session)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    _bind(test_client, company_id, rule)
    pr = _fixture("pr27.json")
    pr["user"] = author
    _install_backfill(
        monkeypatch,
        pr,
        _fixture("commits27.json"),
        (FIXTURES / "pr27.diff").read_text(),
    )

    response = _backfill(test_client, company_id)

    assert response.json()["ingested"] == expected_ingested
    assert response.json()["skipped"] == 1
    assert (
        sqlite_session.exec(
            select(AgentRun).where(AgentRun.company_id == company_id)
        ).all()
        == []
    )


def test_company_cannot_backfill_another_companys_repository(
    sqlite_session, test_client
):
    company_a = _make_company(sqlite_session, "Company A")
    company_b = _make_company(sqlite_session, "Company B")
    _bind(test_client, company_a)

    response = _backfill(test_client, company_b, repo=f"le-fabrique-{company_a}")

    assert response.status_code == 404


def test_rate_limit_returns_503_with_reset_time(
    sqlite_session, test_client, monkeypatch
):
    company_id = _make_company(sqlite_session)
    _bind(test_client, company_id)

    def limited(*args, **kwargs):
        raise github_adapter.GitHubRateLimited("1790000000")

    monkeypatch.setattr(github_adapter, "fetch_pull_requests", limited)
    response = _backfill(test_client, company_id)

    assert response.status_code == 503
    assert response.json()["detail"]["reset_at"] == "1790000000"
    _no_ingestion(sqlite_session, company_id)


@pytest.mark.parametrize("with_key", [True, False])
def test_binding_encrypts_secret_and_duplicate_returns_conflict(
    sqlite_session, test_client, monkeypatch, with_key
):
    company_id = _make_company(sqlite_session)
    key = Fernet.generate_key().decode() if with_key else None
    monkeypatch.setattr(crypto, "_configured_key", lambda: key)

    response = _bind(test_client, company_id)
    binding = sqlite_session.exec(
        select(GitHubRepoBinding).where(GitHubRepoBinding.company_id == company_id)
    ).one()
    duplicate = _bind(test_client, company_id)

    assert response.status_code == 201
    assert binding.webhook_secret_encrypted.startswith(
        "fernet:" if with_key else "plaintext:"
    )
    assert (
        crypto.decrypt_value(binding.webhook_secret_encrypted) == "test-webhook-secret"
    )
    assert duplicate.status_code == 409
