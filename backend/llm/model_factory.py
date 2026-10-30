"""
LLM Model Factory — multi-model LLM configuration and routing.

Maps each AI agent role to a specific Gemini or DeepSeek model configuration,
caches instantiated ``ChatOpenAI`` objects to avoid recreating HTTP sessions,
and exposes a convenience ``create_completion()`` function used by every
LangGraph node.

Model selection rationale:
- **PO / Architect / SecOps**: Gemini 2.5 Pro — best at natural language,
  architecture and security reasoning.
- **Developer / QA**: DeepSeek Coder — lower latency and cost for code-heavy
  tasks.
- **TechWriter / fallback**: Gemini 2.5 Flash — fast and fluent for
  documentation and general prompts.
- **EngramProcessor**: DeepSeek Coder — deterministic (low temperature) for
  structured JSON extraction from decision summaries.

All requests are routed through the internal LLM proxy (``llm-proxy/app.py``)
so API keys and token budgets are enforced centrally.
"""

import os
import logging
from typing import Any, Optional, Dict
from enum import Enum
from pydantic import BaseModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

class AgentRole(str, Enum):
    """Enumeration of all AI agent roles in the Fabrique workflow."""

    PO = "PO"
    ARCHITECT = "Architect"
    SCRUM_MASTER = "ScrumMaster"
    DEVELOPER = "Developer"
    QA = "QA"
    SECOPS = "SecOps"
    TECH_WRITER = "TechWriter"
    ENGRAM_PROCESSOR = "EngramProcessor"


class LLMConfig(BaseModel):
    """LLM model configuration bound to a specific agent role."""

    model_name: str
    temperature: float = 0.7
    max_tokens: int = 2048


class ModelFactory:
    """
    Factory that instantiates and caches ``ChatOpenAI`` clients per agent role.

    The ``_model_cache`` class variable is intentionally shared across all
    instances so that the same ``ChatOpenAI`` HTTP session is reused throughout
    the process lifetime, reducing connection overhead.
    """

    # Maps each role to its preferred model and generation parameters.
    # Using DeepSeek + Qwen Cloud (token plan) instead of Gemini.
    ROLE_MODEL_MAP: Dict[AgentRole, LLMConfig] = {
        AgentRole.PO:               LLMConfig(model_name="qwen3.7-plus",     temperature=0.3, max_tokens=4096),
        AgentRole.ARCHITECT:        LLMConfig(model_name="qwen3.7-plus",     temperature=0.2, max_tokens=4096),
        AgentRole.SCRUM_MASTER:     LLMConfig(model_name="qwen3.7-plus",     temperature=0.5, max_tokens=2048),
        AgentRole.DEVELOPER:        LLMConfig(model_name="deepseek-v4-pro",  temperature=0.2, max_tokens=4096),
        AgentRole.QA:               LLMConfig(model_name="deepseek-v4-pro",  temperature=0.2, max_tokens=4096),
        AgentRole.SECOPS:           LLMConfig(model_name="qwen3.7-plus",     temperature=0.1, max_tokens=4096),  # precision-critical
        AgentRole.TECH_WRITER:      LLMConfig(model_name="qwen3.6-flash",    temperature=0.4, max_tokens=4096),
        AgentRole.ENGRAM_PROCESSOR: LLMConfig(model_name="deepseek-v4-pro",  temperature=0.1, max_tokens=2048),
    }

    # Class-level cache so each role is instantiated at most once per process.
    _model_cache: Dict[AgentRole, Optional[ChatOpenAI]] = {}

    @staticmethod
    def model_for_role(role: AgentRole) -> str:
        """
        The model id to use for *role*.

        ``NEMOTRON_ROLES`` (comma-separated role names) opts roles into the
        NVIDIA models served by Nebius Token Factory; ``NEMOTRON_MODEL``
        (with ``NEMOTRON_MODEL_STRATEGIC`` / ``_FAST`` overrides) names them.
        Unset means the ``ROLE_MODEL_MAP`` default, so nothing changes for
        existing deployments.
        """
        default = ModelFactory.ROLE_MODEL_MAP[role].model_name
        opted_in = {
            r.strip().lower()
            for r in os.getenv("NEMOTRON_ROLES", "").split(",")
            if r.strip()
        }
        if role.value.lower() not in opted_in:
            return default
        tier_var = {
            AgentRole.PO: "NEMOTRON_MODEL_STRATEGIC",
            AgentRole.ARCHITECT: "NEMOTRON_MODEL_STRATEGIC",
            AgentRole.SECOPS: "NEMOTRON_MODEL_STRATEGIC",
            AgentRole.TECH_WRITER: "NEMOTRON_MODEL_FAST",
        }.get(role, "NEMOTRON_MODEL")
        return os.getenv(tier_var) or os.getenv("NEMOTRON_MODEL", "") or default

    @classmethod
    def get_model(cls, role: AgentRole) -> ChatOpenAI:
        """
        Return (or create and cache) the ``ChatOpenAI`` client for *role*.

        The client is configured to target the internal LLM proxy via
        ``base_url``.  The ``X-Agent-Role`` header lets the proxy apply the
        correct token budget for the calling agent.

        Args:
            role: The agent role whose model is needed.

        Returns:
            A configured ``ChatOpenAI`` instance.
        """
        if role in cls._model_cache:
            return cls._model_cache[role]

        config = cls.ROLE_MODEL_MAP.get(role, LLMConfig(model_name="gemini-2.5-flash"))
        proxy_url = os.getenv("LLM_PROXY_URL", "http://localhost:5100")

        model = ChatOpenAI(
            model=cls.model_for_role(role),
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            # "proxy-managed" signals to the OpenAI SDK that auth is handled externally.
            api_key="proxy-managed",
            base_url=f"{proxy_url}/v1",
            # Forwarded to the proxy for per-role token budget tracking.
            default_headers={"X-Agent-Role": role.value},
        )
        cls._model_cache[role] = model
        return model


# Role names stored on Agent rows that are not AgentRole values, keyed by their
# normalised form (lowercase, no spaces, dashes or underscores).
_ROLE_ALIASES: Dict[str, AgentRole] = {
    # The Reviewer agent judges deliverables, as QA does.
    "reviewer": AgentRole.QA,
    "dev": AgentRole.DEVELOPER,
    "backenddev": AgentRole.DEVELOPER,
    "frontenddev": AgentRole.DEVELOPER,
    "fullstackdev": AgentRole.DEVELOPER,
    "mobiledev": AgentRole.DEVELOPER,
    "dataengineer": AgentRole.DEVELOPER,
    "mlengineer": AgentRole.DEVELOPER,
    "devops": AgentRole.DEVELOPER,
    "productowner": AgentRole.PO,
    "sm": AgentRole.SCRUM_MASTER,
    "security": AgentRole.SECOPS,
    "support": AgentRole.TECH_WRITER,
}


def _normalise_role(role: str) -> str:
    return "".join(ch for ch in (role or "").lower() if ch not in " -_")


def role_for_name(role: str) -> AgentRole:
    """
    Map a stored role string to an ``AgentRole``.

    Matches ``AgentRole`` values case-insensitively, then the aliases above;
    anything else is treated as ``AgentRole.DEVELOPER``, as
    ``get_llm_for_role`` does.
    """
    key = _normalise_role(role)
    for candidate in AgentRole:
        if _normalise_role(candidate.value) == key:
            return candidate
    return _ROLE_ALIASES.get(key, AgentRole.DEVELOPER)


def default_model_for_role(role: str) -> str:
    """
    The model id an agent of *role* uses when its own ``model`` is empty.

    This is the single source of role defaults: the LangGraph producer and
    the task worker both read ``ModelFactory.ROLE_MODEL_MAP``.
    """
    return ModelFactory.ROLE_MODEL_MAP[role_for_name(role)].model_name


def get_llm_for_role(role: str) -> ChatOpenAI:
    """
    Convenience wrapper that converts a role *string* to an ``AgentRole`` enum.

    Falls back to ``AgentRole.DEVELOPER`` for unknown role strings to avoid
    hard failures in dynamic caller contexts (e.g. LangGraph state machines).

    Args:
        role: String role name (must match an ``AgentRole`` value).

    Returns:
        Configured ``ChatOpenAI`` instance.
    """
    try:
        return ModelFactory.get_model(AgentRole(role))
    except Exception:
        # Unknown or invalid role — fall back to the Developer model.
        return ModelFactory.get_model(AgentRole.DEVELOPER)


def create_completion(role: str, prompt: str, system_message: Optional[str] = None, bu_id: Optional[int] = None) -> str:
    """
    Execute a single-turn LLM completion for the given agent role with Governance.

    Args:
        role:           Agent role string (e.g. ``"Architect"``).
        prompt:         User-turn prompt text.
        system_message: Optional system instruction.
        bu_id:          Optional Business Unit ID for token quota enforcement.

    Returns:
        The model's text response as a plain string.

    Raises:
        RuntimeError: If the LLM proxy is unreachable or returns an error,
                      so callers can map it to a structured error state.
    """
    try:
        model = get_llm_for_role(role)
    except Exception as e:
        raise RuntimeError(f"Failed to initialise LLM for role '{role}': {e}") from e

    messages = []
    if system_message:
        messages.append(SystemMessage(content=system_message))
    messages.append(HumanMessage(content=prompt))

    config: Dict[str, Any] = {}
    if bu_id:
        config["headers"] = {"X-Business-Unit-ID": str(bu_id)}

    try:
        return model.invoke(messages, **config).content
    except Exception as e:
        # Log with full traceback so the request ID shows up in the logs.
        logger.error(
            "LLM completion failed for role=%s bu_id=%s: %s",
            role, bu_id, e, exc_info=True,
        )
        raise RuntimeError(
            f"LLM proxy error for role '{role}': {type(e).__name__}: {e}"
        ) from e
