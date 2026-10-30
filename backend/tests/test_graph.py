"""
Tests for the LangGraph agent graph (backend/agents/graph.py).

No network calls are made — LLMProxyClient.chat_async is monkeypatched to
return canned responses, and the engram processor is stubbed out.

Run with:
    cd backend && PYTHONPATH=.:app python3 -m pytest tests/test_graph.py -q
"""

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canned_result(content: str = "OK", quota_warning: bool = False) -> dict:
    """Build a minimal OpenAI-style chat response dict."""
    result = {
        "choices": [{"message": {"content": content}}],
    }
    if quota_warning:
        result["quota_warning"] = True
        result["quota_used"] = 900_000
        result["quota_limit"] = 1_000_000
    return result


# ---------------------------------------------------------------------------
# _resolve_model_name
# ---------------------------------------------------------------------------


def test_resolve_model_name_known_role():
    from agents.graph import _resolve_model_name

    model = _resolve_model_name("PO")
    assert model == "qwen3.7-plus"


def test_resolve_model_name_unknown_role_falls_back_to_developer():
    from agents.graph import _resolve_model_name
    from llm.model_factory import AgentRole, ModelFactory

    expected = ModelFactory.ROLE_MODEL_MAP[AgentRole.DEVELOPER].model_name
    assert _resolve_model_name("UnknownRole") == expected


# ---------------------------------------------------------------------------
# _extract_backlog
# ---------------------------------------------------------------------------


def test_extract_backlog_parses_bullet_lines():
    from agents.graph import _extract_backlog

    story = """
Sprint: Alpha
- Build the login page
- Write unit tests
* Deploy to staging
No-bullet line
"""
    items = _extract_backlog(story)
    assert items == ["Build the login page", "Write unit tests", "Deploy to staging"]


def test_extract_backlog_empty_when_no_bullets():
    from agents.graph import _extract_backlog

    story = "Sprint kickoff: no bullets here"
    assert _extract_backlog(story) == []


# ---------------------------------------------------------------------------
# Graph compilation and node order
# ---------------------------------------------------------------------------


def test_create_agent_graph_compiles():
    """create_agent_graph() must return a compiled graph without raising."""
    from agents.graph import create_agent_graph

    graph = create_agent_graph()
    assert graph is not None


def test_create_agent_graph_has_expected_nodes():
    """The compiled graph exposes all expected node names."""
    from agents.graph import create_agent_graph

    graph = create_agent_graph()
    # LangGraph stores nodes on the underlying graph object
    node_names = set(graph.get_graph().nodes.keys())
    expected = {
        "kickoff",
        "po",
        "architect",
        "scrum_master",
        "developer",
        "po_wrap",
        "burn",
        "rejection",
    }
    assert expected.issubset(node_names), f"Missing nodes: {expected - node_names}"


def test_route_entry_goes_to_kickoff_without_feedback():
    """_route_entry returns 'kickoff' when po_feedback is absent."""
    from agents.graph import _route_entry

    state = {
        "interaction_id": "x",
        "story": "do stuff",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": None,
        "company_id": None,
        "business_unit_id": None,
        "sprint_id": None,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": None,
        "publish_event": None,
    }
    assert _route_entry(state) == "kickoff"


def test_route_entry_goes_to_rejection_with_feedback():
    """_route_entry returns 'rejection' when po_feedback is set."""
    from agents.graph import _route_entry

    state = {
        "interaction_id": "x",
        "story": "do stuff",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": "Needs more clarity",
        "company_id": None,
        "business_unit_id": None,
        "sprint_id": None,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": None,
        "publish_event": None,
    }
    assert _route_entry(state) == "rejection"


def test_route_from_sends_to_burn_on_error():
    """_route_from returns the fallback ('burn') when last_error is set."""
    from agents.graph import _route_from

    state = {
        "interaction_id": "x",
        "story": "do stuff",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": None,
        "company_id": None,
        "business_unit_id": None,
        "sprint_id": None,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": "something went wrong",
        "needs_split": None,
        "publish_event": None,
    }
    assert _route_from(state, fallback="burn", success="architect") == "burn"


def test_route_from_sends_to_success_when_no_error():
    """_route_from returns the success node when last_error is absent."""
    from agents.graph import _route_from

    state = {
        "interaction_id": "x",
        "story": "do stuff",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": None,
        "company_id": None,
        "business_unit_id": None,
        "sprint_id": None,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": None,
        "publish_event": None,
    }
    assert _route_from(state, fallback="burn", success="architect") == "architect"


# ---------------------------------------------------------------------------
# _invoke_agent — event publication and quota warning
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invoke_agent_publishes_agent_start_message_complete():
    """_invoke_agent must publish agent_start, message, and agent_complete events."""
    from agents.graph import _invoke_agent

    published: list[dict] = []

    async def fake_publish(event: dict) -> None:
        published.append(event)

    state = {
        "interaction_id": "inv-1",
        "story": "build something",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": None,
        "company_id": 1,
        "business_unit_id": None,
        "sprint_id": 42,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": None,
        "publish_event": fake_publish,
    }

    with patch(
        "agents.graph.LLMProxyClient.chat_async",
        new=AsyncMock(return_value=_canned_result("Sure, I'll do it")),
    ):
        content = await _invoke_agent(
            state, "Developer", "Write tests", "Please write tests"
        )

    assert content == "Sure, I'll do it"
    event_types = [e["type"] for e in published]
    assert "agent_start" in event_types
    assert "message" in event_types
    assert "agent_complete" in event_types


@pytest.mark.asyncio
async def test_invoke_agent_emits_quota_warning_when_flagged():
    """_invoke_agent publishes a quota.warning event when the proxy signals quota_warning."""
    from agents.graph import _invoke_agent

    published: list[dict] = []

    async def fake_publish(event: dict) -> None:
        published.append(event)

    state = {
        "interaction_id": "inv-quota",
        "story": "build something",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": None,
        "company_id": 1,
        "business_unit_id": None,
        "sprint_id": 7,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": None,
        "publish_event": fake_publish,
    }

    with patch(
        "agents.graph.LLMProxyClient.chat_async",
        new=AsyncMock(return_value=_canned_result("answer", quota_warning=True)),
    ):
        await _invoke_agent(state, "PO", "Plan sprint", "Plan it")

    warning_events = [e for e in published if e.get("type") == "quota.warning"]
    assert len(warning_events) == 1
    w = warning_events[0]
    assert w["quota_used"] == 900_000
    assert w["quota_limit"] == 1_000_000


@pytest.mark.asyncio
async def test_invoke_agent_raises_on_error_response():
    """_invoke_agent raises RuntimeError when the proxy returns an error key."""
    from agents.graph import _invoke_agent

    state = {
        "interaction_id": "inv-err",
        "story": "broken",
        "messages": [],
        "backlog_items": [],
        "next_agent": "",
        "created_at": "2026-01-01",
        "po_feedback": None,
        "company_id": 1,
        "business_unit_id": None,
        "sprint_id": 1,
        "openproject_ticket_id": None,
        "engram_id": None,
        "last_error": None,
        "needs_split": None,
        "publish_event": None,
    }

    with (
        patch(
            "agents.graph.LLMProxyClient.chat_async",
            new=AsyncMock(return_value={"error": "rate limited"}),
        ),
        pytest.raises(RuntimeError, match="rate limited"),
    ):
        await _invoke_agent(state, "Developer", "task", "prompt")
