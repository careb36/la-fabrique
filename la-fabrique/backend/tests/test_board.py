"""
services/board.py: how a task's comment thread is read.

- A carry-over note quotes another task's verdict and never counts as this
  task's: a clone keeps its retry.
- A person's send-back note and the gates' verdicts are neither a deliverable
  nor the end of the pending rework; every rework budget restarts after a
  send-back. A person's other notes may be a deliverable, as before.
- A gate's "manual triage" verdict settles the task on its own.
- The worker's console-advice note quotes an assistant and is never a
  verdict; only the worker's own note marks a task as advised, and an advised
  task's rework counts from that note on.
- The Architect's brief is never a verdict either, and the phrases that keep
  a task blocked count only from the system, the gates or a person, not from
  a deliverable; a briefed task's rework counts from the brief on.
"""

from models import BacklogItem
from services import board
from services.orchestration_metrics import (
    ARCHITECT_COMMENT_AUTHOR,
    format_architect_consult_comment,
)

TRIAGE = (
    "Pre-review quality gate failed after 2 rework(s) — blocked for manual triage: x"
)
SEND_BACK = {"author": "user", "text": "Sent back to work by a person."}


def test_a_carried_over_clone_keeps_its_retry_and_its_reason_is_its_own():
    comments = [
        {
            "author": "System",
            "text": f'Carried over from task 7 ("Sprint 0"), which was blocked: {TRIAGE}',
        },
        {"author": "System", "text": "Agent error: proxy 503"},
    ]

    assert board.blocked_item_next_step(comments, "QA") == "retry"
    assert board.block_reason(comments) == "Agent error: proxy 503"
    assert (
        board.has_manual_freeze_marker(
            [
                {
                    "author": "System",
                    "text": 'Carried over from task 7 ("S"), which was blocked: freeze after sleep-induced churn',
                }
            ]
        )
        is False
    )


def test_the_original_marked_as_carried_still_reads_its_own_verdict():
    comments = [
        {"author": "Quality gate", "text": TRIAGE},
        {
            "author": "System",
            "text": 'Carried over to sprint 3 ("Sprint 1") as task 9 by ana.',
        },
    ]

    assert board.blocked_item_next_step(comments, "QA") is None
    assert board.block_reason(comments) == TRIAGE


def test_pending_rework_survives_a_gate_verdict_and_a_send_back():
    comments = [
        {"author": "Dev", "text": "# Artifact: a.py\nprint(1)"},
        {"author": "QA", "text": "NEEDS WORK: add a test for empty input"},
        {"author": "Quality gate", "text": TRIAGE},
        SEND_BACK,
    ]

    assert board.pending_rework_feedback(comments) == [
        "QA: NEEDS WORK: add a test for empty input"
    ]
    assert board.extract_latest_reviewable_comment(comments, "Developer") == ""


def test_a_persons_note_is_never_the_deliverable():
    """A note a Manager leaves on the board goes to nobody's review; the
    task runs again instead (see test_sprint_close)."""
    comments = [
        {"author": "Dev", "text": "# Artifact: a.py\nprint(1)"},
        {"author": "QA", "text": "NEEDS WORK: add a test"},
        {"author": "user", "text": "Please try once more, and mind the edge cases."},
    ]

    assert board.extract_latest_reviewable_comment(comments, "Developer") == ""
    assert board.pending_rework_feedback(comments) == ["QA: NEEDS WORK: add a test"]


def test_rework_budgets_restart_after_a_send_back():
    comments = [
        {"author": "Quality gate", "text": "NEEDS WORK: too short"},
        {"author": "Quality gate", "text": "NEEDS WORK: too short"},
        {"author": "Quality gate", "text": TRIAGE},
        SEND_BACK,
        {"author": "Quality gate", "text": "NEEDS WORK: too short"},
    ]

    assert board.rework_requests_by(comments, "Quality gate") == 1
    assert board.rework_requests_by(comments[:3], "Quality gate") == 2
    assert board.rework_requests_by(comments, "Verifier") == 0


def test_a_gate_verdict_settles_the_task_without_a_prior_rework_request():
    comments = [
        {
            "author": "Verifier",
            "text": "Tests failed after 0 rework(s) — blocked for manual triage: exit 1",
        }
    ]

    assert board.blocked_item_next_step(comments, "Developer") is None
    assert board.item_is_settled(
        BacklogItem(sprint_id=1, title="t", status="blocked", comments=comments)
    )


def test_every_rework_request_counts_once_whoever_made_it():
    comments = [
        {"author": "Dev", "text": "# Artifact: a.py\nprint(1)"},
        {"author": "QA", "text": "needs work: add a test"},
        {"author": "Verifier", "text": "NEEDS WORK: delivery refuted"},
        {"author": "Quality gate", "text": "NEEDS WORK: too short"},
        {"author": "Quality gate", "text": TRIAGE},
        SEND_BACK,
        {
            "author": "System",
            "text": 'Carried over to sprint 3 ("S") as task 9 by ana. NEEDS WORK: not this one',
        },
    ]

    assert board.rework_request_count(comments) == 3
    assert board.rework_request_count([]) == 0
    assert board.rework_request_count("not json") == 0


ADVICE = {
    "author": "System",
    "text": (
        f"{board.CONSOLE_ADVICE_PREFIX}\n- GitHub Copilot CLI (incremental "
        "implementation guidance): add retry logic; needs manual triage if the "
        "API keeps failing. Agent error: handling missing deliverable."
    ),
}


def test_an_assistants_words_are_never_read_as_a_verdict():
    comments = [ADVICE, {"author": "System", "text": "Agent error: proxy 503"}]

    # Not "retried already" (its "retry"), not "manual triage", not the reason.
    assert board.blocked_item_next_step(comments, "Developer") == "retry"
    assert board.block_reason(comments) == "Agent error: proxy 503"
    assert board.block_reason([ADVICE]) == ""
    assert not board.item_is_settled(
        BacklogItem(sprint_id=1, title="t", status="blocked", comments=comments)
    )


def test_only_the_workers_note_marks_a_task_as_advised():
    look_alike = {"author": "Dev", "text": ADVICE["text"]}
    persons = {"author": "user", "text": ADVICE["text"]}

    assert board.has_console_advice([ADVICE]) is True
    assert board.has_console_advice([look_alike, persons]) is False


def test_an_advised_tasks_rework_counts_from_the_advice_on():
    tally = board.no_console_advice()
    # Attempt 1 ran without advice and drew a request; attempt 2 was advised.
    board.count_console_advice(
        tally,
        "done",
        [
            {"author": "Dev", "text": "# Artifact: a.py"},
            {"author": "QA", "text": "NEEDS WORK: add a test"},
            ADVICE,
            {"author": "Dev", "text": "# Artifact: a.py, with a test"},
            {"author": "QA", "text": "NEEDS WORK: cover the empty case"},
            {"author": "QA", "text": "APPROVED: done"},
        ],
    )
    board.count_console_advice(
        tally, "blocked", [{"author": "QA", "text": "NEEDS WORK: again"}]
    )

    assert tally == {
        "advised": {"total": 1, "done": 1, "rework": 1},
        "unadvised": {"total": 1, "done": 0, "rework": 1},
    }


BRIEF = {
    "author": ARCHITECT_COMMENT_AUTHOR,
    "text": format_architect_consult_comment(
        "Handle the missing deliverable case; on agent error: retry once, then "
        "manual triage. NEEDS WORK: nothing yet."
    ),
}


def test_the_architects_brief_is_never_read_as_a_verdict():
    deliverable = {"author": "Dev", "text": "# Artifact: a.py\nprint(1)"}

    # A deliverable and no verdict: it goes back to review, whatever the brief says.
    assert board.blocked_item_next_step([BRIEF, deliverable], "Developer") == "review"
    assert board.block_reason([BRIEF]) == ""
    assert board.rework_request_count([BRIEF]) == 0


def test_a_deliverables_words_are_not_a_block_reason():
    deliverable = {
        "author": "Dev",
        "text": "def run():\n    raise RuntimeError('agent error: missing deliverable')",
    }
    stopped = {"author": "System", "text": "Agent error: proxy 503"}

    assert board.blocked_item_next_step([deliverable], "Developer") == "review"
    # The same words from the system still keep it from review.
    assert board.blocked_item_next_step([deliverable, stopped], "Developer") == "retry"


def test_a_briefed_tasks_rework_counts_from_the_brief_on():
    tally = board.no_architect_advice()
    rework = {"author": "QA", "text": "NEEDS WORK: add a test"}
    board.count_architect_advice(tally, "done", [rework, BRIEF, rework])
    board.count_architect_advice(tally, "blocked", [rework])
    # The worker's console note is not the Architect's brief.
    board.count_architect_advice(tally, "done", [ADVICE])

    assert tally == {
        "advised": {"total": 1, "done": 1, "rework": 1},
        "unadvised": {"total": 2, "done": 1, "rework": 1},
    }
