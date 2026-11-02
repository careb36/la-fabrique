from llm.model_factory import (
    AgentRole,
    ModelFactory,
    create_completion,
    default_model_for_role,
)


def test_role_model_map_uses_deepseek_and_qwen_models():
    assert ModelFactory.ROLE_MODEL_MAP[AgentRole.PO].model_name == "qwen3.7-plus"
    assert ModelFactory.ROLE_MODEL_MAP[AgentRole.ARCHITECT].model_name == "qwen3.7-plus"
    assert (
        ModelFactory.ROLE_MODEL_MAP[AgentRole.SCRUM_MASTER].model_name == "qwen3.7-plus"
    )
    assert ModelFactory.ROLE_MODEL_MAP[AgentRole.SECOPS].model_name == "qwen3.7-plus"
    assert (
        ModelFactory.ROLE_MODEL_MAP[AgentRole.TECH_WRITER].model_name == "qwen3.6-flash"
    )
    assert (
        ModelFactory.ROLE_MODEL_MAP[AgentRole.DEVELOPER].model_name == "deepseek-v4-pro"
    )
    assert ModelFactory.ROLE_MODEL_MAP[AgentRole.QA].model_name == "deepseek-v4-pro"
    assert (
        ModelFactory.ROLE_MODEL_MAP[AgentRole.ENGRAM_PROCESSOR].model_name
        == "deepseek-v4-pro"
    )


def test_create_completion_passes_bu_header(monkeypatch):
    captured = {}

    class _Response:
        content = "ok"

    class _DummyModel:
        def invoke(self, messages, **config):
            captured["config"] = config
            return _Response()

    monkeypatch.setattr(
        "llm.model_factory.get_llm_for_role", lambda _role: _DummyModel()
    )

    result = create_completion(role="Developer", prompt="hello", bu_id=7)

    assert result == "ok"
    assert captured["config"] == {"headers": {"X-Business-Unit-ID": "7"}}


def test_a_role_can_be_given_its_own_model_from_any_provider(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL_DEVELOPER", "nvidia/nemotron-3-super-120b-a12b")
    monkeypatch.setenv("AGENT_MODEL_QA", "gemini-2.5-flash")

    assert (
        ModelFactory.model_for_role(AgentRole.DEVELOPER)
        == "nvidia/nemotron-3-super-120b-a12b"
    )
    assert ModelFactory.model_for_role(AgentRole.QA) == "gemini-2.5-flash"
    # A role nobody named keeps its default.
    assert ModelFactory.model_for_role(AgentRole.SCRUM_MASTER) == "qwen3.7-plus"


def test_a_roles_own_model_wins_over_the_one_for_every_role(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("AGENT_MODEL_SCRUMMASTER", "qwen3.7-plus")
    monkeypatch.setenv("AGENT_MODEL_TECHWRITER", "   ")  # blank: not an override

    assert ModelFactory.model_for_role(AgentRole.SCRUM_MASTER) == "qwen3.7-plus"
    assert ModelFactory.model_for_role(AgentRole.TECH_WRITER) == "deepseek-v4-pro"
    assert ModelFactory.model_for_role(AgentRole.PO) == "deepseek-v4-pro"


def test_the_old_vendor_variables_change_nothing(monkeypatch):
    """The per-vendor opt-in of earlier releases is gone: only the neutral variables are read."""
    monkeypatch.setenv("NEMOTRON_ROLES", "developer")
    monkeypatch.setenv("NEMOTRON_MODEL", "nvidia/Nemotron-Ultra")

    assert ModelFactory.model_for_role(AgentRole.DEVELOPER) == "deepseek-v4-pro"


def test_agent_model_overrides_every_role(monkeypatch):
    """One provider key must be enough to run every agent."""
    monkeypatch.setenv("AGENT_MODEL", "gemini-flash-latest")

    for role in AgentRole:
        assert ModelFactory.model_for_role(role) == "gemini-flash-latest"


def test_the_worker_and_the_graph_read_the_same_override(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "gemini-flash-latest")

    assert default_model_for_role("QA") == "gemini-flash-latest"
    assert default_model_for_role("Developer") == "gemini-flash-latest"


def test_without_agent_model_the_role_map_is_untouched(monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)

    assert default_model_for_role("QA") == "deepseek-v4-pro"
