"""
Who opens a sprint's Glassroom stream.

A browser EventSource cannot send an Authorization header, so with
authentication required the stream takes a short-lived ticket for one sprint,
issued to a Viewer of its company; membership is checked again when the
ticket is used. Without a ticket (or with someone else's) nothing streams,
and no connection is registered for it.
"""

import secrets
from datetime import timedelta

import auth_tokens
import pytest
from config import settings
from models import Company, CompanyMember, Sprint, User
from routers import agents
from routers.agents import sse_connections


@pytest.fixture(autouse=True)
def enforcement(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    key = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth_tokens, "_configured_key", lambda: key)


@pytest.fixture
def board(sqlite_session, monkeypatch):
    monkeypatch.setattr(agents, "engine", sqlite_session.get_bind())
    company = Company(company_name=f"Glassroom {secrets.token_hex(3)}")
    sqlite_session.add(company)
    sqlite_session.commit()
    sprint = Sprint(company_id=company.id, sprint_name="S")
    sqlite_session.add(sprint)
    sqlite_session.commit()
    return company, sprint


def _person(session, company=None, role="Viewer"):
    user = User(
        email=f"glass-{secrets.token_hex(6)}@example.com",
        full_name="Glass",
        password_hash="unused",
    )
    session.add(user)
    session.commit()
    if company is not None:
        session.add(
            CompanyMember(company_id=company.id, user_id=user.id, human_role=role)
        )
        session.commit()
    token = auth_tokens.create_access_token(user_id=user.id, email=user.email)
    return user, {"Authorization": f"Bearer {token}"}


def _stream(test_client, sprint_id, ticket=None):
    params = {"sprint_id": str(sprint_id)}
    if ticket is not None:
        params["ticket"] = ticket
    return test_client.get("/v1/glassroom/stream", params=params)


def test_a_viewer_gets_a_ticket_for_the_sprint(test_client, sqlite_session, board):
    company, sprint = board
    viewer, headers = _person(sqlite_session, company)

    response = test_client.post(
        f"/v1/sprints/{sprint.id}/stream_ticket", headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] == auth_tokens.STREAM_TICKET_MINUTES * 60
    assert auth_tokens.decode_stream_ticket(body["ticket"], sprint.id) == viewer.id


def test_no_ticket_outside_the_company_or_without_a_login(
    test_client, sqlite_session, board
):
    _company, sprint = board
    _outsider, headers = _person(sqlite_session)

    assert (
        test_client.post(
            f"/v1/sprints/{sprint.id}/stream_ticket", headers=headers
        ).status_code
        == 403
    )
    assert test_client.post(f"/v1/sprints/{sprint.id}/stream_ticket").status_code == 401


@pytest.mark.parametrize(
    "ticket",
    [None, "not-a-ticket", "access-token", "other-sprint", "expired"],
)
def test_the_stream_refuses_anything_but_a_ticket_for_this_sprint(
    test_client, sqlite_session, board, ticket
):
    company, sprint = board
    viewer, _ = _person(sqlite_session, company)
    other = Sprint(company_id=company.id, sprint_name="Other")
    sqlite_session.add(other)
    sqlite_session.commit()
    tickets = {
        None: None,
        "not-a-ticket": "not-a-ticket",
        "access-token": auth_tokens.create_access_token(
            user_id=viewer.id, email=viewer.email
        ),
        "other-sprint": auth_tokens.create_stream_ticket(
            user_id=viewer.id, sprint_id=other.id
        ),
        "expired": auth_tokens.create_stream_ticket(
            user_id=viewer.id, sprint_id=sprint.id, expires_delta=timedelta(seconds=-1)
        ),
    }

    response = _stream(test_client, sprint.id, tickets[ticket])

    assert response.status_code == 401
    assert str(sprint.id) not in sse_connections


def test_a_ticket_stops_working_once_its_holder_leaves_the_company(
    test_client, sqlite_session, board
):
    company, sprint = board
    viewer, _ = _person(sqlite_session, company)
    ticket = auth_tokens.create_stream_ticket(user_id=viewer.id, sprint_id=sprint.id)
    membership = sqlite_session.query(CompanyMember).filter_by(user_id=viewer.id).one()
    sqlite_session.delete(membership)
    sqlite_session.commit()

    response = _stream(test_client, sprint.id, ticket)

    assert response.status_code == 403
    assert str(sprint.id) not in sse_connections


def test_the_check_lets_a_members_ticket_through(sqlite_session, board):
    company, sprint = board
    viewer, _ = _person(sqlite_session, company)
    ticket = auth_tokens.create_stream_ticket(user_id=viewer.id, sprint_id=sprint.id)

    # No exception: the stream then opens as before (covered by test_glassroom_sse).
    agents._check_stream_ticket(str(sprint.id), ticket)
