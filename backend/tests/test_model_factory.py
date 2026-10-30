from llm.model_factory import AgentRole, ModelFactory, create_completion


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


def test_nemotron_roles_opt_in_overrides_the_default_model(monkeypatch):
    monkeypatch.setenv("NEMOTRON_ROLES", "developer, qa")
    monkeypatch.setenv("NEMOTRON_MODEL", "nvidia/Llama-3.1-Nemotron-70B-Instruct")

    assert (
        ModelFactory.model_for_role(AgentRole.DEVELOPER)
        == "nvidia/Llama-3.1-Nemotron-70B-Instruct"
    )
    assert (
        ModelFactory.model_for_role(AgentRole.QA)
        == "nvidia/Llama-3.1-Nemotron-70B-Instruct"
    )
    # A role that did not opt in keeps its default.
    assert ModelFactory.model_for_role(AgentRole.SCRUM_MASTER) == "qwen3.7-plus"


def test_nemotron_tier_overrides_pick_the_right_size(monkeypatch):
    monkeypatch.setenv("NEMOTRON_ROLES", "PO,TechWriter")
    monkeypatch.setenv("NEMOTRON_MODEL_STRATEGIC", "nvidia/Nemotron-Ultra")
    monkeypatch.setenv("NEMOTRON_MODEL_FAST", "nvidia/Nemotron-Nano-9B")

    assert ModelFactory.model_for_role(AgentRole.PO) == "nvidia/Nemotron-Ultra"
    assert (
        ModelFactory.model_for_role(AgentRole.TECH_WRITER) == "nvidia/Nemotron-Nano-9B"
    )


def test_without_nemotron_roles_nothing_changes(monkeypatch):
    monkeypatch.delenv("NEMOTRON_ROLES", raising=False)
    monkeypatch.setenv("NEMOTRON_MODEL", "nvidia/Nemotron-Ultra")

    assert ModelFactory.model_for_role(AgentRole.DEVELOPER) == "deepseek-v4-pro"
