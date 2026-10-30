"""Who sees and changes support tickets: support admins versus reporters."""

import secrets

import auth_tokens
import pytest
from config import settings
from models import BugReport, Company, CompanyMember, User


@pytest.fixture(autouse=True)
def enforcement(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SUPPORT_ADMIN_EMAILS", "")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path))
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)


def _user(session, label):
    user = User(
        email=f"{label}-{secrets.token_hex(6)}@example.com",
        full_name=label,
        password_hash="unused",
    )
    session.add(user)
    session.commit()
    headers = {
        "Authorization": "Bearer "
        + auth_tokens.create_access_token(user_id=user.id, email=user.email)
    }
    return user, headers


def _ticket(session, reporter_email):
    report = BugReport(
        ticket_num=f"FAB-T{secrets.token_hex(4).upper()}",
        title="Board does not load",
        description="Spinner forever",
        reporter_email=reporter_email,
    )
    session.add(report)
    session.commit()
    return report


@pytest.fixture
def people(sqlite_session, monkeypatch):
    admin, admin_headers = _user(sqlite_session, "admin")
    reporter, reporter_headers = _user(sqlite_session, "reporter")
    other, _ = _user(sqlite_session, "other")
    # Configured with different case and spacing on purpose.
    monkeypatch.setattr(
        settings, "SUPPORT_ADMIN_EMAILS", f" {admin.email.upper()} , x@y.z"
    )
    mine = _ticket(sqlite_session, reporter.email.upper())
    theirs = _ticket(sqlite_session, other.email)
    return {
        "admin": admin_headers,
        "reporter": reporter_headers,
        "reporter_email": reporter.email,
        "mine": mine.ticket_num,
        "theirs": theirs.ticket_num,
    }


def _nums(response):
    return {ticket["ticket_num"] for ticket in response.json()["tickets"]}


def test_reporter_lists_only_their_own_tickets(test_client, people):
    response = test_client.get("/v1/support/tickets", headers=people["reporter"])
    assert response.status_code == 200
    assert _nums(response) == {people["mine"]}

    by_email = test_client.get(
        "/v1/support/tickets",
        params={"reporter_email": people["reporter_email"]},
        headers=people["reporter"],
    )
    assert _nums(by_email) == {people["mine"]}


def test_reporter_cannot_ask_for_someone_elses_tickets(test_client, people):
    response = test_client.get(
        "/v1/support/tickets",
        params={"reporter_email": "someone@example.com"},
        headers=people["reporter"],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "You can only see your own tickets"}


def test_reporter_reads_own_ticket_but_not_others(test_client, people):
    own = test_client.get(
        f"/v1/support/tickets/{people['mine']}", headers=people["reporter"]
    )
    assert own.status_code == 200
    other = test_client.get(
        f"/v1/support/tickets/{people['theirs']}", headers=people["reporter"]
    )
    assert other.status_code == 404


@pytest.mark.parametrize(
    "method, path",
    [("PATCH", "/v1/support/tickets/{num}"), ("GET", "/v1/support/logs")],
)
def test_only_admins_triage(test_client, people, method, path):
    response = test_client.request(
        method,
        path.format(num=people["mine"]),
        json={"status": "resolved", "resolution": "done"},
        headers=people["reporter"],
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Requires support admin"}


def test_admin_sees_everything_and_triages(test_client, people, sqlite_session):
    listed = test_client.get(
        "/v1/support/tickets", params={"limit": 200}, headers=people["admin"]
    )
    assert {people["mine"], people["theirs"]} <= _nums(listed)
    detail = test_client.get(
        f"/v1/support/tickets/{people['theirs']}", headers=people["admin"]
    )
    assert detail.status_code == 200

    patched = test_client.patch(
        f"/v1/support/tickets/{people['theirs']}",
        json={"status": "resolved", "resolution": "Restarted the worker"},
        headers=people["admin"],
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "resolved"
    # No audit log written yet in this test's AUDIT_LOG_PATH.
    assert (
        test_client.get("/v1/support/logs", headers=people["admin"]).status_code == 404
    )


def test_admin_decides_severity_and_category_apart_from_the_reporter(
    test_client, people, sqlite_session
):
    patched = test_client.patch(
        f"/v1/support/tickets/{people['mine']}",
        json={"status": "in_progress", "severity": "critical", "category": "incident"},
        headers=people["admin"],
    )
    assert patched.status_code == 200
    assert (patched.json()["decided_severity"], patched.json()["decided_category"]) == (
        "critical",
        "incident",
    )
    detail = test_client.get(
        f"/v1/support/tickets/{people['mine']}", headers=people["admin"]
    ).json()
    # The reporter's choice stays as they made it (none); the decision sits beside it.
    assert (detail["severity"], detail["category"]) == (None, None)
    assert (detail["decided_severity"], detail["decided_category"]) == (
        "critical",
        "incident",
    )
    assert detail["decided_by"].endswith("@example.com")
    assert detail["decided_at"] is not None

    # A later update that decides only the category keeps the severity decided.
    test_client.patch(
        f"/v1/support/tickets/{people['mine']}",
        json={"status": "waiting", "category": "bug"},
        headers=people["admin"],
    )
    again = test_client.get(
        f"/v1/support/tickets/{people['mine']}", headers=people["admin"]
    ).json()
    assert (again["decided_severity"], again["decided_category"]) == ("critical", "bug")


def test_resolved_at_is_the_time_the_ticket_was_resolved(test_client, people):
    url = f"/v1/support/tickets/{people['mine']}"

    def resolved_at():
        return test_client.get(url, headers=people["admin"]).json()["resolved_at"]

    def save(**fields):
        assert (
            test_client.patch(url, json=fields, headers=people["admin"]).status_code
            == 200
        )

    save(status="resolved", resolution="Fixed")
    first = resolved_at()
    assert first is not None
    # A later save of the resolved ticket (a decision, say) keeps that time.
    save(status="resolved", category="bug")
    assert resolved_at() == first
    # Reopened, the ticket is not resolved; closed again, the time is new.
    save(status="open")
    assert resolved_at() is None
    save(status="closed")
    assert resolved_at() is not None


def test_a_decision_is_credited_to_whoever_changed_it_and_can_be_cleared(
    test_client, people, sqlite_session, monkeypatch
):
    second, second_headers = _user(sqlite_session, "second")
    monkeypatch.setattr(
        settings,
        "SUPPORT_ADMIN_EMAILS",
        f"{settings.SUPPORT_ADMIN_EMAILS},{second.email}",
    )
    url = f"/v1/support/tickets/{people['mine']}"

    def decision():
        detail = test_client.get(url, headers=people["admin"]).json()
        return (
            detail["decided_severity"],
            detail["decided_category"],
            (detail["decided_by"] or "").split("-")[0],
        )

    test_client.patch(
        url, json={"status": "in_progress", "severity": "high"}, headers=people["admin"]
    )
    # Saving the same decision with a new status is not deciding again.
    test_client.patch(
        url, json={"status": "waiting", "severity": "high"}, headers=second_headers
    )
    assert decision() == ("high", None, "admin")

    test_client.patch(
        url, json={"status": "waiting", "category": "Incident"}, headers=second_headers
    )
    assert decision() == ("high", "incident", "second")

    cleared = test_client.patch(
        url, json={"status": "waiting", "severity": ""}, headers=second_headers
    )
    assert cleared.status_code == 200
    assert decision() == (None, "incident", "second")
    test_client.patch(
        url, json={"status": "waiting", "category": " "}, headers=second_headers
    )
    assert decision() == (None, None, "")
    assert test_client.get(url, headers=people["admin"]).json()["decided_at"] is None


def test_the_impact_filter_reads_the_decision_first(
    test_client, people, sqlite_session
):
    def ticket(severity, decided):
        report = _ticket(sqlite_session, "filter@example.com")
        report.severity, report.decided_severity = severity, decided
        sqlite_session.add(report)
        sqlite_session.commit()
        return report.ticket_num

    reported_high = ticket("high", None)
    decided_high = ticket("low", "high")
    overruled = ticket("high", "low")
    legacy = ticket("High", None)

    def listed(severity):
        response = test_client.get(
            "/v1/support/tickets",
            params={"severity": severity, "reporter_email": "filter@example.com"},
            headers=people["admin"],
        )
        assert response.status_code == 200
        return _nums(response)

    assert listed("high") == {reported_high, decided_high, legacy}
    assert listed(" LOW ") == {overruled}


def test_the_reporters_choice_is_normalized_and_nothing_is_made_up(
    test_client, sqlite_session
):
    def report(**fields):
        return test_client.post(
            "/v1/support/report_bug",
            json={"title": "Board does not load", "description": "Spinner", **fields},
        )

    chosen = report(severity="High ", category=" Bug").json()["id"]
    unchosen = report().json()["id"]
    sqlite_session.expire_all()
    assert (
        sqlite_session.get(BugReport, chosen).severity,
        sqlite_session.get(BugReport, chosen).category,
    ) == ("high", "bug")
    assert (
        sqlite_session.get(BugReport, unchosen).severity,
        sqlite_session.get(BugReport, unchosen).category,
    ) == (None, None)
    refused = report(severity="urgent")
    assert refused.status_code == 400
    assert refused.json()["detail"].startswith("Invalid severity.")


@pytest.mark.parametrize("field, value", [("severity", "urgent"), ("category", "rant")])
def test_an_unknown_decision_is_refused(test_client, people, field, value):
    response = test_client.patch(
        f"/v1/support/tickets/{people['mine']}",
        json={"status": "open", field: value},
        headers=people["admin"],
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith(f"Invalid {field}.")


def test_only_admins_read_the_agents_record(test_client, people):
    assert (
        test_client.get(
            "/v1/support/agent_record", headers=people["reporter"]
        ).status_code
        == 403
    )
    record = test_client.get("/v1/support/agent_record", headers=people["admin"])
    assert record.status_code == 200
    assert set(record.json()) == {"severity", "category"}


def test_auth_me_reports_support_admin(test_client, people):
    assert (
        test_client.get("/v1/auth/me", headers=people["admin"]).json()["support_admin"]
        is True
    )
    assert (
        test_client.get("/v1/auth/me", headers=people["reporter"]).json()[
            "support_admin"
        ]
        is False
    )


def test_no_admins_configured_means_nobody_triages(test_client, people, monkeypatch):
    monkeypatch.setattr(settings, "SUPPORT_ADMIN_EMAILS", "")
    response = test_client.get("/v1/support/logs", headers=people["admin"])
    assert response.status_code == 403


def test_demo_without_auth_keeps_the_desk_open(test_client, people, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", False)
    response = test_client.get("/v1/support/tickets", params={"limit": 200})
    assert response.status_code == 200
    assert {people["mine"], people["theirs"]} <= _nums(response)


def test_reinviting_a_member_is_a_conflict(test_client, sqlite_session):
    owner, owner_headers = _user(sqlite_session, "owner")
    guest, _ = _user(sqlite_session, "guest")
    company = Company(company_name="Invite conflict")
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.add(
        CompanyMember(company_id=company.id, user_id=owner.id, human_role="Owner")
    )
    sqlite_session.commit()
    body = {"company_id": company.id, "email": guest.email, "human_role": "Manager"}

    assert (
        test_client.post(
            "/v1/company/invite", json=body, headers=owner_headers
        ).status_code
        == 200
    )
    again = test_client.post(
        "/v1/company/invite",
        json={**body, "human_role": "Viewer"},
        headers=owner_headers,
    )
    assert again.status_code == 409
    assert again.json() == {"detail": f"{guest.email} is already a member as Manager"}
