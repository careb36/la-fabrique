"""Opt-in authentication, company roles, and legacy compatibility."""

import secrets
from unittest.mock import MagicMock

import auth_tokens
import pytest
from auth_policy import require_authenticated, require_company_role
from config import settings
from fastapi import HTTPException
from models import (
    AuditLog,
    BacklogItem,
    BusinessUnit,
    Company,
    CompanyMember,
    Sprint,
    User,
)
from models.agent_run import AgentRun
from models.github import GitHubRepoBinding
from services.company_service import CompanyService
from sqlmodel import select
from test_github_adapter import _webhook


@pytest.fixture(autouse=True)
def enforcement(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))


@pytest.fixture
def signing_key(monkeypatch):
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)
    return key


@pytest.fixture
def identity(sqlite_session, signing_key):
    user = User(
        email=f"auth-{secrets.token_hex(8)}@example.com",
        full_name="Authenticated reviewer",
        password_hash="unused",
    )
    company = Company(company_name="Authorization test")
    sqlite_session.add(user)
    sqlite_session.add(company)
    sqlite_session.commit()
    headers = {
        "Authorization": "Bearer "
        + auth_tokens.create_access_token(user_id=user.id, email=user.email)
    }
    return user, company, headers


def _member(session, identity, role):
    user, company, _ = identity
    member = CompanyMember(company_id=company.id, user_id=user.id, human_role=role)
    session.add(member)
    session.commit()
    return member


def _run(session, company_id):
    run = AgentRun(
        company_id=company_id,
        external_ref=f"auth:{secrets.token_hex(8)}",
        producer="test",
        artifact_digest="unused",
        artifact_size=0,
    )
    session.add(run)
    session.commit()
    return run


def _approval(company_id):
    return {
        "company_id": company_id,
        "approver_name": "Payload Reviewer",
        "decision": "approved",
    }


def test_list_requires_bearer_challenge(test_client):
    response = test_client.get("/v1/agent_runs", params={"company_id": 1})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("company_id", [1, 99999999])
def test_nonmember_gets_403_not_company_existence(test_client, identity, company_id):
    response = test_client.get(
        "/v1/agent_runs", params={"company_id": company_id}, headers=identity[2]
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Not a member of this company"}


def test_viewer_can_list_but_not_approve(test_client, sqlite_session, identity):
    _member(sqlite_session, identity, "Viewer")
    run = _run(sqlite_session, identity[1].id)
    listed = test_client.get(
        "/v1/agent_runs", params={"company_id": run.company_id}, headers=identity[2]
    )
    assert listed.status_code == 200
    assert run.id in [item["id"] for item in listed.json()["agent_runs"]]
    response = test_client.post(
        f"/v1/agent_runs/{run.id}/approve",
        json=_approval(run.company_id),
        headers=identity[2],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Requires Manager role"}


def test_manager_approval_preserves_payload_audit_identity(
    test_client, sqlite_session, identity
):
    _member(sqlite_session, identity, "Manager")
    run = _run(sqlite_session, identity[1].id)
    response = test_client.post(
        f"/v1/agent_runs/{run.id}/approve",
        json=_approval(run.company_id),
        headers=identity[2],
    )
    assert response.status_code == 201
    audit = sqlite_session.get(AuditLog, response.json()["audit_log_id"])
    assert audit.agent_id == "human:Payload Reviewer"
    assert audit.action == "agent_run_approved"


@pytest.mark.parametrize("role, expected", [("Manager", 403), ("Owner", 200)])
def test_only_owner_can_invite(test_client, sqlite_session, identity, role, expected):
    _member(sqlite_session, identity, role)
    invitee = User(
        email=f"invite-{secrets.token_hex(8)}@example.com",
        full_name="Invitee",
        password_hash="unused",
    )
    sqlite_session.add(invitee)
    sqlite_session.commit()
    response = test_client.post(
        "/v1/company/invite",
        json={
            "company_id": identity[1].id,
            "email": invitee.email,
            "human_role": "Owner",
        },
        headers=identity[2],
    )
    assert response.status_code == expected
    memberships = sqlite_session.exec(
        select(CompanyMember).where(CompanyMember.user_id == invitee.id)
    ).all()
    if expected == 403:
        assert response.json() == {"detail": "Requires Owner role"}
        assert memberships == []
    else:
        assert len(memberships) == 1
        assert memberships[0].human_role == "Owner"
        assert memberships[0].company_id == identity[1].id


@pytest.fixture
def company_services(monkeypatch):
    monkeypatch.setattr(
        "services.company_service.plan_foundation_sprint",
        lambda **kwargs: {"goal": "Test", "tasks": []},
    )
    monkeypatch.setattr(CompanyService, "_seed_neo4j", lambda *args: None)


def test_init_requires_token(test_client):
    response = test_client.post("/v1/init_company", json={"company_name": "Denied"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_init_creates_exactly_one_owner(
    test_client, sqlite_session, identity, company_services
):
    response = test_client.post(
        "/v1/init_company", json={"company_name": "Owned"}, headers=identity[2]
    )
    assert response.status_code == 200
    members = sqlite_session.exec(
        select(CompanyMember).where(
            CompanyMember.company_id == response.json()["company_id"]
        )
    ).all()
    assert len(members) == 1
    assert members[0].user_id == identity[0].id
    assert members[0].human_role == "Owner"


def test_owner_bootstrap_rolls_back_with_company(
    test_client, sqlite_session, identity, company_services, monkeypatch
):
    def fail_plan(**kwargs):
        raise RuntimeError("Planning failed")

    monkeypatch.setattr("services.company_service.plan_foundation_sprint", fail_plan)
    response = test_client.post(
        "/v1/init_company", json={"company_name": "Rollback"}, headers=identity[2]
    )
    assert response.status_code == 500
    sqlite_session.rollback()
    assert (
        sqlite_session.exec(
            select(Company).where(Company.company_name == "Rollback")
        ).all()
        == []
    )
    assert (
        sqlite_session.exec(
            select(CompanyMember).where(CompanyMember.user_id == identity[0].id)
        ).all()
        == []
    )


def test_signed_webhook_stays_public(test_client, sqlite_session, identity):
    company_id = identity[1].id
    repo = f"auth-public-{company_id}"
    sqlite_session.add(
        GitHubRepoBinding(
            company_id=company_id,
            owner="careb36",
            repo=repo,
            webhook_secret_encrypted="plaintext:test-webhook-secret",
        )
    )
    sqlite_session.commit()
    response = _webhook(test_client, {}, event="ping", repository=f"careb36/{repo}")
    assert response.status_code == 204


def test_flag_off_list_ignores_invalid_token(test_client, monkeypatch, identity):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    for headers in ({}, {"Authorization": "******"}):
        response = test_client.get(
            "/v1/agent_runs", params={"company_id": identity[1].id}, headers=headers
        )
        assert response.status_code == 200
        assert response.json() == {"agent_runs": []}


def test_flag_off_approve_without_token(
    test_client, sqlite_session, identity, monkeypatch
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    run = _run(sqlite_session, identity[1].id)
    response = test_client.post(
        f"/v1/agent_runs/{run.id}/approve", json=_approval(run.company_id)
    )
    assert response.status_code == 201
    assert response.json()["approver_name"] == "Payload Reviewer"


def test_flag_off_init_creates_no_membership(
    test_client, sqlite_session, monkeypatch, company_services
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    response = test_client.post("/v1/init_company", json={"company_name": "Legacy"})
    assert response.status_code == 200
    assert (
        sqlite_session.exec(
            select(CompanyMember).where(
                CompanyMember.company_id == response.json()["company_id"]
            )
        ).all()
        == []
    )


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/v1/agent_runs?company_id=1"),
        ("POST", "/v1/agent_runs"),
        ("GET", "/v1/agent_runs/1?company_id=1"),
        ("GET", "/v1/agent_runs/1/verifications?company_id=1"),
        ("GET", "/v1/agent_runs/1/approvals?company_id=1"),
        ("POST", "/v1/agent_runs/1/verify"),
        ("POST", "/v1/agent_runs/1/approve"),
        ("POST", "/v1/plan_sprint"),
        ("POST", "/v1/plan_self_improvement_sprint"),
        ("POST", "/v1/start_sprint"),
        ("POST", "/v1/sprints/1/dispatch"),
        ("PATCH", "/v1/backlog/1"),
        ("GET", "/v1/sprints/1/board"),
        ("GET", "/v1/sprints?company_id=1"),
        ("POST", "/v1/generate"),
        ("POST", "/v1/audit"),
        ("POST", "/v1/memory/store?content=test"),
        ("GET", "/v1/memory/search?query=test"),
        ("GET", "/v1/audit/verify?interaction_id=test"),
        ("GET", "/v1/audit/chain?company_id=1"),
        ("GET", "/v1/messages?company_id=1"),
        ("GET", "/v1/procedures?company_id=1"),
        ("POST", "/v1/procedures"),
        ("POST", "/v1/procedures/1/adopt"),
        ("GET", "/v1/support/tickets"),
        ("GET", "/v1/support/tickets/FAB-00001"),
        ("PATCH", "/v1/support/tickets/FAB-00001"),
        ("GET", "/v1/support/logs"),
        ("POST", "/v1/integrations/github/bindings"),
        ("POST", "/v1/integrations/github/backfill"),
        ("GET", "/v1/enterprise/quotas?company_id=1"),
        ("POST", "/v1/enterprise/quotas/1/reset"),
        ("GET", "/v1/analytics/summary?sprint_id=1"),
        ("GET", "/v1/analytics/orchestration_health?company_id=1"),
        ("GET", "/v1/enterprise/lineage?file_path=test"),
        ("POST", "/v1/discover_team"),
        ("POST", "/v1/company/invite"),
        ("GET", "/v1/workspace/status"),
        ("GET", "/v1/workspace/browse"),
        ("GET", "/v1/workspace/inspect?path=/tmp"),
    ],
)
def test_protected_route_requires_token(test_client, method, path):
    response = test_client.request(method, path, json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_sprint_scope_uses_owning_company(test_client, sqlite_session, identity):
    _member(sqlite_session, identity, "Owner")
    other = Company(company_name="Other tenant")
    sqlite_session.add(other)
    sqlite_session.flush()
    sprint = Sprint(company_id=other.id, sprint_name="Private", start_date="2026-10-17")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    response = test_client.get(f"/v1/sprints/{sprint.id}/board", headers=identity[2])
    assert response.status_code == 403
    assert response.json() == {"detail": "Not a member of this company"}


@pytest.mark.parametrize("role, expected", [("Viewer", 403), ("Manager", 200)])
def test_backlog_and_dispatch_roles(
    test_client, sqlite_session, identity, role, expected
):
    _member(sqlite_session, identity, role)
    sprint = Sprint(
        company_id=identity[1].id, sprint_name="Scoped", start_date="2026-10-17"
    )
    sqlite_session.add(sprint)
    sqlite_session.flush()
    item = BacklogItem(sprint_id=sprint.id, title="Scoped item")
    sqlite_session.add(item)
    sqlite_session.commit()
    updated = test_client.patch(
        f"/v1/backlog/{item.id}", json={"status": "done"}, headers=identity[2]
    )
    dispatched = test_client.post(
        f"/v1/sprints/{sprint.id}/dispatch", headers=identity[2]
    )
    assert updated.status_code == expected
    assert dispatched.status_code == expected
    sqlite_session.refresh(item)
    assert item.status == ("done" if expected == 200 else "todo")


@pytest.mark.parametrize(
    "path", ["/v1/sprints/99999999/board", "/v1/analytics/summary?sprint_id=99999999"]
)
def test_missing_sprint_stays_404(test_client, identity, path):
    response = test_client.get(path, headers=identity[2])
    assert response.status_code == 404
    assert response.json() == {"detail": "Sprint not found"}


def test_missing_backlog_stays_404(test_client, identity):
    response = test_client.patch(
        "/v1/backlog/99999999", json={"status": "done"}, headers=identity[2]
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Backlog item not found"}


def test_authentication_guard_and_flag_off_role_noop(sqlite_session, monkeypatch):
    with pytest.raises(HTTPException) as exc:
        require_authenticated(None)
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    assert require_authenticated(None) is None
    assert require_company_role(sqlite_session, None, 99999999, "Owner") is None


@pytest.mark.parametrize("role", [None, "Viewer"])
@pytest.mark.parametrize(
    "path, payload",
    [
        ("/v1/generate", {"story": "Test"}),
        ("/v1/audit", {"action": "test"}),
        ("/v1/memory/store?content=test", None),
        (
            "/v1/integrations/github/bindings",
            {
                "owner": "test",
                "repo": "test",
                "webhook_secret": "test-only",
            },
        ),
        ("/v1/integrations/github/backfill", {"owner": "test", "repo": "test"}),
        ("/v1/plan_sprint", {"prompt": "Test"}),
        ("/v1/plan_self_improvement_sprint", {}),
        (
            "/v1/start_sprint",
            {
                "sprint_name": "Test",
                "start_date": "2026-10-17",
                "backlog_items": [],
            },
        ),
    ],
)
def test_company_mutations_require_manager(
    test_client, sqlite_session, identity, role, path, payload
):
    if role:
        _member(sqlite_session, identity, role)
    company_id = identity[1].id
    # La query se compone aquí: pasar `params=` descarta la que ya lleva `path`
    # en el client de Starlette 1.x, y estos casos prueban el orden entre la
    # validación del cuerpo y la autorización.
    url = f"{path}{'&' if '?' in path else '?'}company_id={company_id}"
    response = test_client.post(
        url,
        json={**payload, "company_id": company_id} if payload is not None else None,
        headers=identity[2],
    )
    assert response.status_code == 403
    assert response.json() == {
        "detail": "Requires Manager role" if role else "Not a member of this company"
    }


@pytest.mark.parametrize("role, expected", [("Viewer", 403), ("Manager", 200)])
def test_quota_reset_uses_business_unit_company(
    test_client, sqlite_session, identity, role, expected
):
    _member(sqlite_session, identity, role)
    unit = BusinessUnit(
        company_id=identity[1].id, unit_name="Test", token_quota_used=123
    )
    sqlite_session.add(unit)
    sqlite_session.commit()
    response = test_client.post(
        f"/v1/enterprise/quotas/{unit.id}/reset", headers=identity[2]
    )
    assert response.status_code == expected
    sqlite_session.refresh(unit)
    assert unit.token_quota_used == (0 if expected == 200 else 123)


@pytest.mark.parametrize(
    "path",
    [
        "/v1/enterprise/quotas",
        "/v1/analytics/orchestration_health",
        "/v1/enterprise/lineage?file_path=test",
    ],
)
def test_enterprise_reads_reject_nonmembers(test_client, identity, path):
    url = f"{path}{'&' if '?' in path else '?'}company_id={identity[1].id}"
    response = test_client.get(url, headers=identity[2])
    assert response.status_code == 403
    assert response.json() == {"detail": "Not a member of this company"}


@pytest.mark.parametrize("enabled", [True, False])
def test_lineage_query_uses_company_column(
    test_client, sqlite_session, identity, monkeypatch, enabled
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", enabled)
    _member(sqlite_session, identity, "Viewer")
    driver = MagicMock()
    neo_session = driver.session.return_value.__enter__.return_value
    neo_session.run.return_value = [{"engram_id": "owned-engram"}]
    monkeypatch.setattr("routers.enterprise.get_neo4j_driver", lambda: driver)

    response = test_client.get(
        "/v1/enterprise/lineage",
        params={"file_path": "src/main.py", "company_id": identity[1].id},
        headers=identity[2] if enabled else {},
    )

    assert response.status_code == 200
    assert response.json()["lineage"] == [{"engram_id": "owned-engram"}]
    query = neo_session.run.call_args.args[0]
    params = neo_session.run.call_args.kwargs
    assert params["file_path"] == "src/main.py"
    assert params["company_id"] == identity[1].id
    assert "e.company_id = $company_id" in query
    assert "apoc.convert.fromJsonMap" not in query
    assert "e.company_id IS NULL AS legacy" in query


@pytest.mark.parametrize("existing_audit", [False, True])
def test_audit_rejects_another_company_interaction(
    test_client, sqlite_session, identity, existing_audit
):
    _member(sqlite_session, identity, "Manager")
    other = Company(company_name="Other audit owner")
    sqlite_session.add(other)
    sqlite_session.commit()
    run = _run(sqlite_session, other.id)
    interaction_id = f"agent-run:{run.external_ref}"
    if existing_audit:
        sqlite_session.add(
            AuditLog(
                company_id=other.id, interaction_id=interaction_id, action="original"
            )
        )
        sqlite_session.commit()
    response = test_client.post(
        "/v1/audit",
        params={"company_id": identity[1].id},
        json={
            "interaction_id": interaction_id,
            "action": "forged",
            "details": {"company_id": identity[1].id},
        },
        headers=identity[2],
    )
    assert response.status_code == 403
    assert not sqlite_session.exec(
        select(AuditLog).where(
            AuditLog.interaction_id == interaction_id, AuditLog.action == "forged"
        )
    ).all()


def test_audit_verify_hides_nonmember_rows_and_flags_legacy(
    test_client, sqlite_session, identity
):
    _member(sqlite_session, identity, "Viewer")
    other = Company(company_name="Private audit owner")
    sqlite_session.add(other)
    sqlite_session.commit()
    interaction_id = secrets.token_hex(16)
    sqlite_session.add(
        AuditLog(company_id=other.id, interaction_id=interaction_id, action="private")
    )
    sqlite_session.commit()
    params = {"interaction_id": interaction_id}
    assert (
        test_client.get(
            "/v1/audit/verify", params=params, headers=identity[2]
        ).status_code
        == 404
    )
    legacy = AuditLog(interaction_id=interaction_id, action="legacy")
    sqlite_session.add(legacy)
    sqlite_session.commit()
    response = test_client.get("/v1/audit/verify", params=params, headers=identity[2])
    assert response.status_code == 200
    assert response.json()["rows"] == [
        {
            "id": legacy.id,
            "action": "legacy",
            "status": "legacy",
            "mode": "legacy",
            "company_id": None,
            "legacy": True,
        }
    ]
    assert (
        test_client.get(
            "/v1/audit/verify",
            params={**params, "company_id": identity[1].id},
            headers=identity[2],
        ).status_code
        == 404
    )


def test_audit_write_sets_authorized_company_column(
    test_client, sqlite_session, identity
):
    _member(sqlite_session, identity, "Manager")
    interaction_id = secrets.token_hex(16)
    response = test_client.post(
        "/v1/audit",
        params={"company_id": identity[1].id},
        json={"interaction_id": interaction_id, "action": "owned"},
        headers=identity[2],
    )
    assert response.status_code == 200
    row = sqlite_session.exec(
        select(AuditLog).where(AuditLog.interaction_id == interaction_id)
    ).one()
    assert row.company_id == identity[1].id
    response = test_client.get(
        "/v1/audit/verify",
        params={"interaction_id": interaction_id},
        headers=identity[2],
    )
    assert response.json()["rows"][0]["legacy"] is False


@pytest.mark.parametrize("operation", ["audit", "memory/store?content=test"])
def test_payload_company_cannot_override_authorized_context(
    test_client, sqlite_session, identity, operation
):
    _member(sqlite_session, identity, "Manager")
    payload = {"company_id": identity[1].id + 100000}
    if operation == "audit":
        payload = {"action": "forged", "details": payload}
    sep = "&" if "?" in operation else "?"
    response = test_client.post(
        f"/v1/{operation}{sep}company_id={identity[1].id}",
        json=payload,
        headers=identity[2],
    )
    assert response.status_code == 403


@pytest.mark.parametrize("company_filter", [False, True])
def test_memory_search_passes_membership_scope(
    test_client, sqlite_session, identity, company_filter
):
    _member(sqlite_session, identity, "Viewer")
    memory = MagicMock()
    memory.search_similar.return_value = []
    test_client.app.state.memory_client = memory
    params = {"query": "architecture"}
    if company_filter:
        params["company_id"] = identity[1].id
    response = test_client.get("/v1/memory/search", params=params, headers=identity[2])
    assert response.status_code == 200
    memory.search_similar.assert_called_once_with(
        "architecture",
        10,
        company_ids=[identity[1].id],
        include_legacy=not company_filter,
    )


def test_memory_store_passes_server_company(test_client, sqlite_session, identity):
    _member(sqlite_session, identity, "Manager")
    memory = MagicMock()
    test_client.app.state.memory_client = memory
    response = test_client.post(
        "/v1/memory/store",
        params={"content": "decision", "company_id": identity[1].id},
        json={"source": "test"},
        headers=identity[2],
    )
    assert response.status_code == 200
    memory.store.assert_called_once_with(
        "decision", {"source": "test"}, company_id=identity[1].id
    )


def test_memory_store_rejects_foreign_interaction(
    test_client, sqlite_session, identity
):
    _member(sqlite_session, identity, "Manager")
    other = Company(company_name="Private memory owner")
    sqlite_session.add(other)
    sqlite_session.commit()
    run = _run(sqlite_session, other.id)
    response = test_client.post(
        "/v1/memory/store",
        params={"content": "forged", "company_id": identity[1].id},
        json={"interaction_id": f"agent-run:{run.external_ref}"},
        headers=identity[2],
    )
    assert response.status_code == 403


def test_audit_chain_is_read_by_a_member_of_the_company_only(
    test_client, sqlite_session, identity
):
    params = {"company_id": identity[1].id}
    response = test_client.get("/v1/audit/chain", params=params, headers=identity[2])
    assert response.status_code == 403
    _member(sqlite_session, identity, "Viewer")
    response = test_client.get("/v1/audit/chain", params=params, headers=identity[2])
    assert response.status_code == 200
    assert response.json()["company_id"] == identity[1].id
