"""What the worker stops asking twice: a cut-off answer is named, a formless
review gets the format back, the short answers are capped."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from services import (
    answers,
    reviewer_agent,
    scrum_master,
    sprint_planner,
    support_agent,
)
from services import task_worker as tw


def test_a_cut_off_answer_is_named_instead_of_asked_for_again_in_full():
    """ "Deliver the complete result again" after a length cut gets it cut again;
    the gate asks for fewer or smaller files instead."""
    fences = "Unbalanced code fences (likely truncated output)"
    assert answers.gate_reason(fences, "length") == answers.CUT_OFF_REASON
    assert answers.gate_reason(fences, "stop") == fences
    assert answers.gate_reason(fences, None) == fences
    assert "fewer or smaller files" in answers.CUT_OFF_REASON
    # The worker reads the gate's reason through the same function.
    assert tw._gate_reason is answers.gate_reason


def test_the_finish_reason_is_read_from_the_proxy_s_answer():
    finish = answers.llm_finish_reason
    assert finish({"choices": [{"finish_reason": "length"}]}) == "length"
    assert finish({"choices": [{"message": {"content": "x"}}]}) is None
    assert finish({}) is None


def test_a_formless_review_is_asked_again_with_the_format_named():
    assert answers.review_format_reminder(0) == ""
    once = answers.review_format_reminder(1)
    assert (
        "previous answer" in once and "'APPROVED:'" in once and "'NEEDS WORK:'" in once
    )
    assert "previous answers" in answers.review_format_reminder(2)


def test_the_short_answers_are_capped_and_the_deliverable_is_not():
    """A review is two or three sentences and a brief a few paragraphs; the
    Developer's deliverable carries every file in full, so it has no cap."""
    assert 0 < answers.REVIEW_MAX_TOKENS <= 1024
    assert 0 < answers.BRIEF_MAX_TOKENS <= 2048
    assert 0 < scrum_master.ANSWER_MAX_TOKENS <= 2048
    assert 0 < support_agent.ANSWER_MAX_TOKENS <= 1024
    assert 0 < reviewer_agent.ANSWER_MAX_TOKENS <= 1024
    assert 0 < sprint_planner.PLAN_MAX_TOKENS <= 8192
    source = Path(tw.__file__).read_text(encoding="utf-8")
    execute = source[
        source.index("def _execute_task(") : source.index("def _consult_architect(")
    ]
    assert "max_tokens" not in execute


def test_every_wait_follows_the_proxy_s_budget():
    """A shorter wait than the proxy's discards an answer already billed."""
    from llm_proxy_client import DEFAULT_TIMEOUT_SECONDS

    assert scrum_master.TIMEOUT_SECONDS == DEFAULT_TIMEOUT_SECONDS
    assert scrum_master.TRIAGE_TIMEOUT_SECONDS == DEFAULT_TIMEOUT_SECONDS
    for module in (sprint_planner, support_agent, reviewer_agent, tw):
        assert "client.timeout = " not in Path(module.__file__).read_text(
            encoding="utf-8"
        ), module.__name__
