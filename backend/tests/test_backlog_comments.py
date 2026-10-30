"""
Backlog comments must survive in-place appends.

The task worker loads ``item.comments``, appends to that list and assigns the
same object back.  On a plain ``JSON`` column SQLAlchemy does not see the
change, so every comment after the first was dropped — including the agent's
deliverable, which QA then reported as missing.
"""

import json

from models.company import Company
from models.sprint import BacklogItem, Sprint
from services import task_worker
from sqlmodel import Session, text


def _item(session: Session) -> int:
    company = Company(company_name="Comments Corp", autonomy_level=1)
    session.add(company)
    session.commit()
    session.refresh(company)
    sprint = Sprint(company_id=company.id, sprint_name="S", scope_size="S")
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    item = BacklogItem(sprint_id=sprint.id, title="Task", status="todo")
    session.add(item)
    session.commit()
    session.refresh(item)
    return item.id


def _texts(session: Session, item_id: int) -> list[str]:
    session.expire_all()
    return [c["text"] for c in session.get(BacklogItem, item_id).comments]


def test_worker_keeps_every_comment(sqlite_session, monkeypatch):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    item_id = _item(sqlite_session)

    task_worker._update_item_status(item_id, "in_progress", "brief", "Architect")
    task_worker._update_item_status(item_id, "in_progress", "delivery", "System")
    task_worker._update_item_status(item_id, "in_review", "the deliverable", "Dev")

    assert _texts(sqlite_session, item_id) == ["brief", "delivery", "the deliverable"]


def test_in_place_append_on_a_loaded_item_is_persisted(sqlite_session):
    item_id = _item(sqlite_session)
    item = sqlite_session.get(BacklogItem, item_id)
    item.comments = [{"author": "Dev", "text": "first"}]
    sqlite_session.commit()

    # The review loop's pattern: mutate the loaded list, assign it back.
    comments = item.comments
    comments.append({"author": "QA", "text": "APPROVED: looks good"})
    item.comments = comments
    sqlite_session.commit()

    assert _texts(sqlite_session, item_id) == ["first", "APPROVED: looks good"]


def test_legacy_string_comments_are_read_as_a_list(sqlite_session, monkeypatch):
    monkeypatch.setattr(task_worker, "engine", sqlite_session.get_bind())
    item_id = _item(sqlite_session)
    legacy = json.dumps(json.dumps([{"author": "Dev", "text": "old"}]))
    sqlite_session.exec(
        text("UPDATE backlog_items SET comments = :c WHERE id = :i").bindparams(
            c=legacy, i=item_id
        )
    )
    sqlite_session.commit()

    task_worker._update_item_status(item_id, "in_review", "new", "Dev")

    assert _texts(sqlite_session, item_id) == ["old", "new"]
