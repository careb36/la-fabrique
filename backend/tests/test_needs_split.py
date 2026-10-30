"""
Tests for the ``needs_split`` sprint flow in agent_worker.py and task_worker.py.

All database I/O uses the in-memory SQLite engine from conftest.py.
No Postgres, NATS, or LLM proxy connections are made.

Run with:
    cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_needs_split.py -q
"""

from models.company import Company
from models.sprint import BacklogItem, Sprint
from sqlmodel import Session

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_company(session: Session, name: str = "Acme Corp") -> int:
    company = Company(company_name=name, autonomy_level=2)
    session.add(company)
    session.commit()
    session.refresh(company)
    return company.id


def _insert_sprint(session: Session, company_id: int, status: str = "active") -> int:
    sprint = Sprint(
        company_id=company_id,
        sprint_name="Test Sprint",
        scope_size="M",
        status=status,
    )
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    return sprint.id


# ---------------------------------------------------------------------------
# _mark_sprint_needs_split
# ---------------------------------------------------------------------------


def test_mark_sprint_needs_split_sets_status(sqlite_session):
    """_mark_sprint_needs_split transitions an active sprint to 'needs_split'."""
    company_id = _insert_company(sqlite_session, "NeedsSplit Corp")
    sprint_id = _insert_sprint(sqlite_session, company_id, status="active")

    # Patch the module-level engine in agent_worker to use our SQLite engine

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.agent_worker.engine", sqlite_engine):
        from services.agent_worker import _mark_sprint_needs_split

        _mark_sprint_needs_split(sprint_id)

    # Re-read the sprint row from the same session
    sqlite_session.expire_all()
    sprint = sqlite_session.get(Sprint, sprint_id)
    assert sprint is not None
    assert sprint.status == "needs_split"


def test_mark_sprint_needs_split_ignores_already_split(sqlite_session):
    """_mark_sprint_needs_split does not change status when already 'needs_split'."""
    company_id = _insert_company(sqlite_session, "AlreadySplit Corp")
    sprint_id = _insert_sprint(sqlite_session, company_id, status="needs_split")

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.agent_worker.engine", sqlite_engine):
        from services.agent_worker import _mark_sprint_needs_split

        _mark_sprint_needs_split(sprint_id)

    sqlite_session.expire_all()
    sprint = sqlite_session.get(Sprint, sprint_id)
    assert sprint.status == "needs_split"  # unchanged


def test_mark_sprint_needs_split_ignores_completed_sprint(sqlite_session):
    """_mark_sprint_needs_split must not re-open a completed sprint."""
    company_id = _insert_company(sqlite_session, "Completed Corp")
    sprint_id = _insert_sprint(sqlite_session, company_id, status="completed")

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.agent_worker.engine", sqlite_engine):
        from services.agent_worker import _mark_sprint_needs_split

        _mark_sprint_needs_split(sprint_id)

    sqlite_session.expire_all()
    sprint = sqlite_session.get(Sprint, sprint_id)
    assert sprint.status == "completed"  # must stay completed


def test_mark_sprint_needs_split_unknown_id_is_noop(sqlite_session):
    """_mark_sprint_needs_split with a nonexistent sprint_id silently does nothing."""
    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.agent_worker.engine", sqlite_engine):
        from services.agent_worker import _mark_sprint_needs_split

        # Should not raise
        _mark_sprint_needs_split(99999)


# ---------------------------------------------------------------------------
# _complete_sprint_and_plan_follow_up — status-based dispatch guard
# ---------------------------------------------------------------------------


def test_complete_sprint_skips_when_sprint_not_active(sqlite_session):
    """_complete_sprint_and_plan_follow_up returns not-completed for a 'needs_split' sprint."""
    company_id = _insert_company(sqlite_session, "Guard Corp")
    sprint_id = _insert_sprint(sqlite_session, company_id, status="needs_split")

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.task_worker.engine", sqlite_engine):
        from services.task_worker import _complete_sprint_and_plan_follow_up

        result = _complete_sprint_and_plan_follow_up(sprint_id)

    assert result["completed"] is False
    assert result["reason"] == "not_active"


def test_complete_sprint_skips_when_items_not_done(sqlite_session):
    """_complete_sprint_and_plan_follow_up returns not-completed when items remain open."""
    company_id = _insert_company(sqlite_session, "PartialDone Corp")
    sprint_id = _insert_sprint(sqlite_session, company_id, status="active")

    # Add one done item and one todo item
    for status in ("done", "todo"):
        sqlite_session.add(
            BacklogItem(sprint_id=sprint_id, title=f"Item {status}", status=status)
        )
    sqlite_session.commit()

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.task_worker.engine", sqlite_engine):
        from services.task_worker import _complete_sprint_and_plan_follow_up

        result = _complete_sprint_and_plan_follow_up(sprint_id)

    assert result["completed"] is False
    assert result["reason"] == "not_all_done"


def test_complete_sprint_marks_completed_when_all_done(sqlite_session):
    """_complete_sprint_and_plan_follow_up marks status='completed' when all items are done."""
    company_id = _insert_company(sqlite_session, "AllDone Corp")
    sprint_id = _insert_sprint(sqlite_session, company_id, status="active")

    for i in range(2):
        sqlite_session.add(
            BacklogItem(sprint_id=sprint_id, title=f"Item {i}", status="done")
        )
    sqlite_session.commit()

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with patch("services.task_worker.engine", sqlite_engine):
        from services.task_worker import _complete_sprint_and_plan_follow_up

        result = _complete_sprint_and_plan_follow_up(sprint_id)

    assert result["completed"] is True

    sqlite_session.expire_all()
    sprint = sqlite_session.get(Sprint, sprint_id)
    assert sprint.status == "completed"


def test_active_and_needs_split_block_follow_up(sqlite_session):
    """
    When another sprint with status 'active' or 'needs_split' exists for the company,
    _complete_sprint_and_plan_follow_up must not open a new follow-up sprint.

    The autonomy_level must be 3 to reach the blocking check.
    """
    company = Company(company_name="Blocker Corp", autonomy_level=3)
    sqlite_session.add(company)
    sqlite_session.commit()
    sqlite_session.refresh(company)
    company_id = company.id

    # Sprint to be completed (all items done)
    sprint_to_complete_id = _insert_sprint(sqlite_session, company_id, status="active")
    sqlite_session.add(
        BacklogItem(sprint_id=sprint_to_complete_id, title="Work", status="done")
    )

    # Blocking sprint — status can be "active" or "needs_split"
    blocking_sprint = Sprint(
        company_id=company_id,
        sprint_name="Blocker Sprint",
        scope_size="S",
        status="needs_split",
    )
    sqlite_session.add(blocking_sprint)
    sqlite_session.commit()
    sqlite_session.refresh(blocking_sprint)

    sqlite_engine = sqlite_session.get_bind()

    from unittest.mock import patch

    with (
        patch("services.task_worker.engine", sqlite_engine),
        # Also stub out plan_self_improvement_sprint so no LLM call happens
        patch("services.task_worker.AUTO_SELF_IMPROVEMENT_ENABLED", True),
    ):
        from services.task_worker import _complete_sprint_and_plan_follow_up

        result = _complete_sprint_and_plan_follow_up(sprint_to_complete_id)

    # Sprint should still be marked completed
    assert result["completed"] is True
    # But follow-up must be blocked because a needs_split sprint exists
    assert result.get("reason") == "active_sprint_already_exists"
    assert result.get("blocking_sprint_id") == blocking_sprint.id
