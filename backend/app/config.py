"""
Application settings for Fabrique Enterprise Backend.

All values can be overridden by environment variables or a local ``.env`` file.
pydantic-settings automatically reads env vars that match the field names
(case-sensitive by default, see the inner ``Config`` class).

Usage::

    from config import settings
    db_url = settings.POSTGRES_HOST
"""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ---------------------------------------------------------------------------
    # PostgreSQL — primary relational store (companies, sprints, backlog, audit)
    # ---------------------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "factory"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "factory"

    # ---------------------------------------------------------------------------
    # Neo4j — Temporal Knowledge Graph for episodic memory (Engrams)
    # ---------------------------------------------------------------------------
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # ---------------------------------------------------------------------------
    # NATS — asynchronous event bus for agent orchestration and Glassroom SSE
    # ---------------------------------------------------------------------------
    NATS_URL: str = "nats://localhost:4222"

    # ---------------------------------------------------------------------------
    # OpenProject — external project-management tool used by PO / Dev agents
    # In production, tokens should be retrieved from Vault/KMS instead.
    # ---------------------------------------------------------------------------
    OPENPROJECT_URL: str = "http://localhost:8080"
    OPENPROJECT_TOKEN_PO: str | None = None  # Product Owner API token
    OPENPROJECT_TOKEN_DEV: str | None = None  # Developer API token

    # ---------------------------------------------------------------------------
    # LLM Proxy — internal gateway that routes requests to Gemini / DeepSeek
    # ---------------------------------------------------------------------------
    LLM_PROXY_URL: str = "http://localhost:5100"
    # How long the task worker waits for the workspace daemon to confirm file writes.
    WORKSPACE_WRITE_TIMEOUT_SECONDS: float = 30.0
    # After a verified delivery, run the project's tests through the daemon and
    # record the exit status as evidence.  Off by default: it executes
    # agent-written code on the machine running the daemon.
    DELIVERY_TESTS_ENABLED: bool = False
    # Test command to run; empty means detect it (npm test / pytest).
    DELIVERY_TEST_COMMAND: str = ""
    # The daemon itself stops a command after 120 s; wait slightly longer.
    DELIVERY_TEST_TIMEOUT_SECONDS: float = 130.0

    # ---------------------------------------------------------------------------
    # Autonomous improvement & console assistants
    # ---------------------------------------------------------------------------
    AUTO_SELF_IMPROVEMENT_ENABLED: bool = True
    CONSOLE_ASSISTANTS_ENABLED: bool = True
    # The Support agent triages new help-desk tickets (suggested severity and
    # category, a first reply to the reporter). Off by default: reporting a
    # bug is public, and each new ticket costs an LLM call.
    SUPPORT_AGENT_ENABLED: bool = False
    SUPPORT_AGENT_INTERVAL_SECONDS: float = 60.0
    # The Reviewer agent reads the evidence of other producers' runs waiting
    # for a person and suggests the decision; a Manager still decides. Off by
    # default: each run costs an LLM call.
    REVIEWER_AGENT_ENABLED: bool = False
    REVIEWER_AGENT_INTERVAL_SECONDS: float = 60.0
    # Per-call timeout for a console assistant run requested from the daemon.
    CONSOLE_ASSISTANT_TIMEOUT_SECONDS: float = 90.0
    # Consult the Architect agent before Developers start high-priority, design-sensitive
    # or QA-reworked tasks. Emits ``ARCHITECT_CONSULTED:`` comments for analytics.
    ARCHITECT_CONSULT_ENABLED: bool = True
    # Enable the internal LangGraph producer; externally-produced runs use AgentRun ingestion.
    AGENT_GRAPH_ENABLED: bool = False
    COPILOT_CLI_COMMAND_TEMPLATE: str = "copilot -p {prompt} --output-format json"
    CLAUDE_CLI_COMMAND_TEMPLATE: str | None = (
        "claude --print --output-format json --add-dir {workspace_root} --allowedTools {allowed_tools} --append-system-prompt {system_prompt} {prompt}"
    )
    CLAUDE_CLI_ALLOWED_TOOLS: str = "Read,Grep,Glob,LS,Bash(git *)"
    CLAUDE_CLI_APPEND_SYSTEM_PROMPT: str = "You are being used as a bounded external coding advisor. Stay read-mostly, prefer incremental changes, preserve healthy behavior, and return concise actionable guidance for the current repository task."
    CONSOLE_ASSISTANT_STRATEGY: str = "copilot_first"
    CLAUDE_CLI_HIGH_VALUE_ROLES: str = "Architect,PO,QA,ScrumMaster"
    CLAUDE_CLI_DEFAULT_COOLDOWN_MINUTES: int = 10
    CONSOLE_ASSISTANT_ALLOWED_ROLES: str = "Developer,Architect,QA,PO,ScrumMaster"

    # ---------------------------------------------------------------------------
    # Audit — filesystem path for append-only JSONL audit logs
    # ---------------------------------------------------------------------------
    AUDIT_LOG_PATH: str = "/app/.factory/logs"

    # ---------------------------------------------------------------------------
    # Credential encryption — Fernet key for ProjectCredential.encrypted_value.
    # Unset means values are stored with a "plaintext:" prefix and a warning.
    # Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # ---------------------------------------------------------------------------
    FERNET_SECRET_KEY: str | None = None

    # ---------------------------------------------------------------------------
    # Human-user authentication — HS256 signing key for access tokens.
    # ---------------------------------------------------------------------------
    JWT_SECRET_KEY: str | None = None
    AUTH_REQUIRED: bool = True
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ---------------------------------------------------------------------------
    # Voice control — shared secret the desktop assistant presents as
    # ``X-Voice-Key`` on /v1/voice/*. Unset means the voice façade refuses to
    # answer (503) while AUTH_REQUIRED is on; it never opens anonymously.
    # ---------------------------------------------------------------------------
    VOICE_API_KEY: str | None = None
    # Company the voice façade uses when the caller does not name one. Unset
    # means "the oldest company", which is what a single-tenant install wants.
    VOICE_COMPANY_ID: int | None = None

    @field_validator("VOICE_COMPANY_ID", mode="before")
    @classmethod
    def _empty_company_is_unset(cls, value):
        # `.env.example` and docker compose pass it as an empty string.
        return None if isinstance(value, str) and not value.strip() else value

    # Audit signing — separate HMAC key for decision_signature values.
    # ---------------------------------------------------------------------------
    AUDIT_SIGNING_KEY: str | None = None

    # ---------------------------------------------------------------------------
    # GitHub integration — optional token for API rate-limit headroom
    # ---------------------------------------------------------------------------
    GITHUB_TOKEN: str | None = None
    # Address GitHub uses to reach this backend (webhook Payload URL), e.g. a
    # tunnel or the public host. Reported by /v1/capabilities for the frontend.
    PUBLIC_API_URL: str | None = None

    # ---------------------------------------------------------------------------
    # Support desk — accounts (comma-separated emails) that triage every ticket
    # and download the support logs. Other users see only the tickets they
    # reported with their account email.
    # ---------------------------------------------------------------------------
    SUPPORT_ADMIN_EMAILS: str = ""

    # ---------------------------------------------------------------------------
    # LLM API Keys
    # ---------------------------------------------------------------------------
    GEMINI_API_KEY: str | None = None
    DEEPSEEK_API_KEY: str | None = None
    QWEN_API_KEY: str | None = None

    # ---------------------------------------------------------------------------
    # Security — rate limiting and CORS
    # ---------------------------------------------------------------------------
    RATE_LIMIT_DEFAULT: str = "100/minute"
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    SECURITY_HEADERS_ENABLED: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True


# Module-level singleton; import this object rather than instantiating Settings directly.
settings = Settings()
