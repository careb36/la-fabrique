"""
Integration tests for critical end-to-end flows.

Covers:
- Full sprint lifecycle (create → start → execute → complete)
- Authentication flow (register → login → access protected route)
- Agent run ingestion → verification → approval cycle
- GitHub adapter → agent run → verification pipeline
"""

import hashlib
import json
import secrets
from uuid import uuid4

import auth_tokens
import pytest
from config import settings
from models.agent_run import AgentRun, AgentRunApproval
from models.audit import AuditLog
from models.company import Company, CompanyMember, User
from models.sprint import BacklogItem, Sprint
from sqlmodel import select

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def signing_key(monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


def _make_company(session, name="Integration Test Corp"):
    company = Company(company_name=name)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company.id


def _make_user(session, email="test@example.com", password="testpass123"):
    from crypto import hash_password

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name="Test User",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _make_member(session, user_id, company_id, human_role="Owner"):
    member = CompanyMember(
        user_id=user_id,
        company_id=company_id,
        human_role=human_role,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


# ---------------------------------------------------------------------------
# Sprint lifecycle tests
# ---------------------------------------------------------------------------


class TestSprintLifecycle:
    """Test the full sprint lifecycle from creation to completion."""

    def test_sprint_creation_and_retrieval(self, sqlite_session, test_client):
        """Create a sprint and verify it can be retrieved."""
        company_id = _make_company(sqlite_session)

        # Create sprint via API
        response = test_client.post(
            "/v1/start_sprint",
            json={
                "company_id": company_id,
                "sprint_name": "Integration sprint",
                "start_date": "2026-10-17",
                "scope_size": "M",
                "backlog_items": [{"title": f"Task {i}"} for i in range(1, 4)],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["backlog_item_ids"]) == 3
        board_response = test_client.get(body["sprint_url"])
        assert board_response.status_code == 200
        assert board_response.json()["sprint"]["scope_size"] == "M"
        assert board_response.json()["sprint"]["status"] == "active"

        # Verify in database
        sprint = sqlite_session.exec(
            select(Sprint).where(Sprint.company_id == company_id)
        ).one()
        assert sprint.id == body["sprint_id"]
        assert sprint.company_id == company_id
        assert sprint.status == "active"
        items = sqlite_session.exec(
            select(BacklogItem).where(BacklogItem.sprint_id == sprint.id)
        ).all()
        assert len(items) == 3

    def test_sprint_scope_validation(self, sqlite_session, test_client):
        """Verify sprint scope constraints are enforced."""
        company_id = _make_company(sqlite_session)

        # Too many items for scope S
        response = test_client.post(
            "/v1/start_sprint",
            json={
                "company_id": company_id,
                "sprint_name": "Oversized sprint",
                "start_date": "2026-10-17",
                "scope_size": "S",
                "backlog_items": [{"title": f"Task {i}"} for i in range(1, 6)],
            },
        )

        assert response.status_code == 422

    def test_sprint_backlog_item_transitions(self, sqlite_session, test_client):
        """Test backlog item state transitions."""
        company_id = _make_company(sqlite_session)

        response = test_client.post(
            "/v1/start_sprint",
            json={
                "company_id": company_id,
                "sprint_name": "Transition sprint",
                "start_date": "2026-10-17",
                "scope_size": "S",
                "backlog_items": [{"title": "Task 1"}],
            },
        )

        assert response.status_code == 200
        sprint_id = response.json()["sprint_id"]

        # Get the backlog item
        item = sqlite_session.exec(
            select(BacklogItem).where(BacklogItem.sprint_id == sprint_id)
        ).one()
        assert item.status == "todo"

        # Update status
        item.status = "in_progress"
        sqlite_session.add(item)
        sqlite_session.commit()

        # Verify
        updated = sqlite_session.get(BacklogItem, item.id)
        assert updated.status == "in_progress"


# ---------------------------------------------------------------------------
# Authentication flow tests
# ---------------------------------------------------------------------------


class TestAuthenticationFlow:
    """Test the complete authentication flow."""

    def test_register_login_access_protected_route(
        self, sqlite_session, test_client, signing_key
    ):
        """Full auth flow: register → login → access protected route."""
        # Register
        register_response = test_client.post(
            "/v1/auth/register",
            json={
                "email": "auth-test@example.com",
                "password": "securepass123",
                "full_name": "Auth Test User",
            },
        )
        assert register_response.status_code == 200
        _user_id = register_response.json()["user_id"]

        # Login
        login_response = test_client.post(
            "/v1/auth/login",
            json={
                "email": "auth-test@example.com",
                "password": "securepass123",
            },
        )
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        assert token

        # Access protected route
        me_response = test_client.get(
            "/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_response.status_code == 200
        assert me_response.json()["email"] == "auth-test@example.com"

    def test_login_with_wrong_password_fails(
        self, sqlite_session, test_client, signing_key
    ):
        """Verify login fails with wrong password."""
        # Register first
        test_client.post(
            "/v1/auth/register",
            json={
                "email": "wrong-pass@example.com",
                "password": "correctpass123",
            },
        )

        # Try login with wrong password
        response = test_client.post(
            "/v1/auth/login",
            json={
                "email": "wrong-pass@example.com",
                "password": "wrongpass456",
            },
        )
        assert response.status_code == 401

    def test_protected_route_requires_auth(
        self, sqlite_session, test_client, monkeypatch
    ):
        """Verify protected routes reject unauthenticated requests."""
        monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
        response = test_client.get("/v1/auth/me")
        assert response.status_code == 401

        response = test_client.get("/v1/enterprise/quotas", params={"company_id": 1})
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Agent run ingestion → verification → approval cycle
# ---------------------------------------------------------------------------


class TestAgentRunVerificationCycle:
    """Test the complete agent run lifecycle."""

    def test_ingest_verify_approve_cycle(
        self, sqlite_session, test_client, monkeypatch, tmp_path
    ):
        """Full cycle: ingest → verify → approve."""
        monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
        company_id = _make_company(sqlite_session)

        # Ingest
        ingest_response = test_client.post(
            "/v1/agent_runs",
            json={
                "company_id": company_id,
                "external_ref": f"integration:{uuid4()}",
                "producer": "copilot",
                "artifact": "diff --git a/file.py b/file.py",
                "claims": {"summary": "Added feature"},
            },
        )
        assert ingest_response.status_code == 201
        run_id = ingest_response.json()["id"]

        # Verify
        verify_response = test_client.post(
            f"/v1/agent_runs/{run_id}/verify",
            json={
                "company_id": company_id,
                "evidence": {
                    "ci": {
                        "conclusion": "success",
                        "source": "github-check-run",
                        "ref": "run/123",
                    }
                },
            },
        )
        assert verify_response.status_code == 201
        assert verify_response.json()["verdict"] == "verified"

        # Check run status updated
        run = sqlite_session.get(AgentRun, run_id)
        assert run.status == "verified"

        # Approve
        approve_response = test_client.post(
            f"/v1/agent_runs/{run_id}/approve",
            json={
                "company_id": company_id,
                "approver_name": "Test User",
                "decision": "approved",
            },
        )
        assert approve_response.status_code == 201

        # Check approval recorded
        approval = sqlite_session.exec(
            select(AgentRunApproval).where(AgentRunApproval.agent_run_id == run_id)
        ).one()
        assert approval.decision == "approved"

    def test_ingest_refuted_run(
        self, sqlite_session, test_client, monkeypatch, tmp_path
    ):
        """Test that a run with failed CI is refuted."""
        monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
        company_id = _make_company(sqlite_session)

        # Ingest
        ingest_response = test_client.post(
            "/v1/agent_runs",
            json={
                "company_id": company_id,
                "external_ref": "github:test/repo#2",
                "producer": "copilot",
                "artifact": "",
                "claims": {"summary": "All tests pass"},
            },
        )
        run_id = ingest_response.json()["id"]

        # Verify with failed CI
        verify_response = test_client.post(
            f"/v1/agent_runs/{run_id}/verify",
            json={
                "company_id": company_id,
                "evidence": {
                    "ci": {
                        "conclusion": "failure",
                        "source": "github-check-run",
                        "ref": "run/456",
                    }
                },
            },
        )
        assert verify_response.json()["verdict"] == "refuted"

        # Check run status
        run = sqlite_session.get(AgentRun, run_id)
        assert run.status == "refuted"

    def test_cross_tenant_access_denied(
        self, sqlite_session, test_client, monkeypatch, tmp_path
    ):
        """Verify cross-tenant access is properly denied."""
        monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
        company_a = _make_company(sqlite_session, "Company A")
        company_b = _make_company(sqlite_session, "Company B")

        # Ingest for company A
        ingest_response = test_client.post(
            "/v1/agent_runs",
            json={
                "company_id": company_a,
                "external_ref": "github:test/repo#3",
                "producer": "copilot",
                "artifact": "diff",
                "claims": {"summary": "Work"},
            },
        )
        run_id = ingest_response.json()["id"]

        # Try to verify as company B
        verify_response = test_client.post(
            f"/v1/agent_runs/{run_id}/verify",
            json={"company_id": company_b, "evidence": None},
        )
        assert verify_response.status_code == 404


# ---------------------------------------------------------------------------
# GitHub adapter → agent run → verification pipeline
# ---------------------------------------------------------------------------


class TestGitHubToVerificationPipeline:
    """Test the complete GitHub adapter pipeline."""

    def test_github_pr_ingestion_to_verification(
        self, sqlite_session, test_client, monkeypatch, tmp_path
    ):
        """Full pipeline: GitHub PR → agent run → verification."""
        from pathlib import Path

        monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
        company_id = _make_company(sqlite_session)

        # Load fixture
        fixture_path = Path(__file__).parent / "fixtures" / "github" / "pr27.json"
        pr = json.loads(fixture_path.read_text())

        # Bind repository
        bind_response = test_client.post(
            "/v1/integrations/github/bindings",
            json={
                "company_id": company_id,
                "owner": "careb36",
                "repo": "test-repo",
                "webhook_secret": "test-secret",
                "inclusion_rule": "all",
            },
        )
        assert bind_response.status_code == 201

        # Mock GitHub API calls
        from services import github_adapter

        monkeypatch.setattr(
            github_adapter, "fetch_pr_commits", lambda *args, **kwargs: []
        )
        monkeypatch.setattr(github_adapter, "fetch_pr_diff", lambda *args, **kwargs: "")

        # Send webhook
        body = json.dumps(
            {
                "action": "opened",
                "repository": {"full_name": "careb36/test-repo"},
                "pull_request": pr,
            },
            separators=(",", ":"),
        ).encode()

        import hmac

        signature = (
            "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        )

        webhook_response = test_client.post(
            "/v1/integrations/github/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature,
                "X-GitHub-Event": "pull_request",
            },
        )
        assert webhook_response.status_code == 202

        # Verify agent run was created
        run = sqlite_session.exec(
            select(AgentRun).where(AgentRun.company_id == company_id)
        ).one()
        assert run.external_ref == "github:careb36/test-repo#27"
        assert run.producer == "copilot"

        # Verify the run
        verify_response = test_client.post(
            f"/v1/agent_runs/{run.id}/verify",
            json={"company_id": company_id, "evidence": None},
        )
        assert verify_response.status_code == 201
        # Empty diff should be refuted
        assert verify_response.json()["verdict"] == "refuted"


# ---------------------------------------------------------------------------
# Audit trail tests
# ---------------------------------------------------------------------------


class TestAuditTrail:
    """Test that audit trails are properly maintained."""

    def test_agent_run_creates_audit_entry(
        self, sqlite_session, test_client, monkeypatch, tmp_path
    ):
        """Verify that agent run ingestion creates an audit entry."""
        monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
        company_id = _make_company(sqlite_session)

        # Ingest
        test_client.post(
            "/v1/agent_runs",
            json={
                "company_id": company_id,
                "external_ref": "github:test/repo#audit",
                "producer": "copilot",
                "artifact": "diff",
                "claims": {"summary": "Work"},
            },
        )

        # Check audit log
        audits = sqlite_session.exec(
            select(AuditLog).where(
                AuditLog.action == "agent_run_ingested",
                AuditLog.company_id == company_id,
            )
        ).all()
        assert len(audits) == 1

    def test_verification_creates_audit_entry(
        self, sqlite_session, test_client, monkeypatch, tmp_path
    ):
        """Verify that verification creates an audit entry."""
        monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
        company_id = _make_company(sqlite_session)

        # Ingest
        ingest_response = test_client.post(
            "/v1/agent_runs",
            json={
                "company_id": company_id,
                "external_ref": "github:test/repo#audit-verify",
                "producer": "copilot",
                "artifact": "diff",
                "claims": {"summary": "Work"},
            },
        )
        run_id = ingest_response.json()["id"]

        # Verify
        test_client.post(
            f"/v1/agent_runs/{run_id}/verify",
            json={"company_id": company_id, "evidence": None},
        )

        # Check audit log
        audits = sqlite_session.exec(
            select(AuditLog).where(
                AuditLog.action == "agent_run_verified",
                AuditLog.company_id == company_id,
            )
        ).all()
        assert len(audits) == 1
