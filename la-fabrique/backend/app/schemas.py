"""
Pydantic request/response schemas for the Fabrique Enterprise API.

These models are used **exclusively for API validation and serialisation**.
They are intentionally separate from the SQLModel ORM models in ``models/``
to avoid coupling the persistence layer to the HTTP contract.

Naming convention:
- ``*Request``  — inbound request bodies (POST / PATCH payloads).
- ``*Update``   — partial update bodies (PATCH payloads).
- ``Chat*``     — support-chat specific schemas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Request schemas (Pydantic — not persisted directly, used for API validation)
# ---------------------------------------------------------------------------


class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    company_id: int
    external_ref: str
    producer: str
    model: str | None = None
    agent_role: str | None = None
    subject: dict[str, Any] | None = None
    claims: dict[str, Any] | None = None
    artifact: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AgentRunVerificationRequest(BaseModel):
    company_id: int
    evidence: dict[str, Any] | None = None


class CompanyInitRequest(BaseModel):
    """Payload for ``POST /v1/init_company`` — bootstraps a new tenant."""

    company_name: str
    description: str | None = None  # Human-readable factory description
    default_scope_size: str = "M"  # "S" | "M" | "L" — default scope for new sprints
    default_sprint_length_days: int | None = None  # deprecated
    autonomy_level: int = 2  # 1 = human-led, 3 = fully autonomous
    timezone: str = "UTC"  # IANA timezone (e.g. "America/Sao_Paulo")
    agents: list[dict[str, Any]] = []  # List of agent role/persona/budget definitions
    permissions: dict[str, str] | None = None  # credential_type → access_level
    governance: dict[str, bool] | None = (
        None  # Governance gate flags (e.g. require_approval_deploy)
    )
    project_path: str | None = None  # Filesystem path scanned during discovery
    detected_stack: dict[str, Any] | None = None  # Stack analysis from discovery phase


# How many tasks a sprint of each scope may hold, and the ceiling for any.
SCOPE_LIMITS: dict[str, int] = {"S": 4, "M": 8, "L": 12}
SCOPE_HARD_MAX = 12


class SprintStartRequest(BaseModel):
    """Payload for ``POST /v1/start_sprint`` — creates a sprint with initial backlog."""

    company_id: int
    sprint_name: str
    start_date: str  # ISO-8601 date string (e.g. "2026-04-01")
    scope_size: str = "M"  # "S" (≤4 items) | "M" (≤8 items) | "L" (≤12 items)
    goal: str | None = None
    duration_days: int | None = None  # deprecated
    backlog_items: list[
        dict[str, str]
    ]  # Each item has at least "title" and "description"
    # Blocked tasks of earlier sprints to try again in this one (they count
    # towards the scope). Each gets a fresh task carrying what blocked it.
    carry_over_ids: list[int] = []


class SprintPlanRequest(BaseModel):
    """Payload for ``POST /v1/plan_sprint`` — turns a strategic prompt into a sprint backlog."""

    company_id: int
    prompt: str
    scope_size: str = "M"


class SelfImprovementSprintRequest(BaseModel):
    """Payload for ``POST /v1/plan_self_improvement_sprint`` — plans an autonomous improvement sprint."""

    company_id: int
    scope_size: str = "M"


class VoiceCommandRequest(BaseModel):
    """Payload for ``POST /v1/voice/command`` — one spoken factory instruction.

    ``action`` is the small vocabulary the assistant's tool declaration
    exposes; ``text`` carries the dictated objective for the planning actions.
    Every field is optional apart from the action because the assistant may
    leave out whatever the sentence did not say.
    """

    action: str
    company_id: int | None = None
    sprint_id: int | None = None
    run_id: int | None = None
    text: str | None = None
    sprint_name: str | None = None
    scope_size: str | None = None
    feedback: str | None = None
    approver_name: str | None = None
    agent: str | None = None
    language: str | None = None


class GenerateRequest(BaseModel):
    """Payload for ``POST /v1/generate`` — triggers the LangGraph agent workflow."""

    company_id: int
    business_unit_id: int | None = None  # Impute costs to this unit (default if None)
    story: str  # Natural-language user story
    constraints: str | None = None  # Optional technical / business constraints
    interaction_id: str | None = None  # Client-supplied UUID for idempotency


class AuditRequest(BaseModel):
    """Payload for ``POST /v1/audit`` — records an agent decision to the audit log."""

    interaction_id: str | None = None
    agent_id: str | None = None
    action: str  # Short action label (e.g. "generate_code")
    details: dict[str, Any] | None = None  # Arbitrary context for the action
    result: dict[str, Any] | None = None  # Outcome data
    decision_signature: str | None = None  # Deprecated; caller values are ignored
    cost_tokens: int = 0  # Token cost billed to the business unit


class DiscoveryRequest(BaseModel):
    """Payload for ``POST /v1/discover_team`` — analyses a project path."""

    project_path: str  # Absolute or relative path to the project root
    company_id: int | None = None  # Optional for pre-creation discovery


class AgentRunApprovalRequest(BaseModel):
    """Payload for ``POST /v1/agent_runs/{id}/approve`` — human governance action."""

    company_id: int
    approver_name: str
    decision: str  # "approved" | "rejected"
    feedback: str | None = None
    rejection_category: str | None = None  # "scope" | "quality" | "security" | "other"

    @model_validator(mode="after")
    def feedback_required_on_rejection(self) -> "AgentRunApprovalRequest":
        if self.decision not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        self.approver_name = self.approver_name.strip()
        if not self.approver_name:
            raise ValueError("approver_name must not be empty")
        if self.decision == "rejected" and (
            not self.feedback or not self.feedback.strip()
        ):
            raise ValueError("feedback is required when decision is 'rejected'")
        if self.rejection_category is not None:
            if self.rejection_category not in {"scope", "quality", "security", "other"}:
                raise ValueError("invalid rejection_category")
            if self.decision != "rejected":
                raise ValueError("rejection_category is only allowed with 'rejected'")
        return self


class UserCreateRequest(BaseModel):
    """Payload for ``POST /v1/auth/register`` — creates a human platform user."""

    email: str
    full_name: str
    password: str  # Plain-text; hashed with bcrypt before storage


class LoginRequest(BaseModel):
    """Payload for ``POST /v1/auth/login`` — authenticates a human user."""

    email: str
    password: str


class InviteMemberRequest(BaseModel):
    """Payload for ``POST /v1/company/invite`` — adds a user to a company."""

    company_id: int
    email: str
    human_role: str  # "Owner" | "Manager" | "Viewer"


class BacklogItemUpdate(BaseModel):
    """Payload for ``PATCH /v1/backlog/{item_id}`` — partial backlog item update."""

    status: str | None = None  # See VALID_STATUSES in sprint router
    priority: str | None = None  # See VALID_PRIORITIES in sprint router
    assignee: str | None = None
    comment: str | None = None  # When provided, a new comment is appended


class BugReportRequest(BaseModel):
    """Payload for ``POST /v1/support/report_bug`` — creates a support ticket."""

    title: str
    description: str
    steps: str | None = None  # Reproduction steps
    expected: str | None = None  # Expected behaviour
    actual: str | None = None  # Actual (buggy) behaviour
    # "low" | "medium" | "high" | "critical" and "bug" | "feature" | "question"
    # | "incident": what the reporter chose, or nothing. A default would pass
    # for the reporter's choice.
    severity: str | None = None
    category: str | None = None
    reporter_email: str | None = None
    browser_info: dict[str, Any] | None = None  # User-agent, viewport, etc.


class BugStatusUpdateRequest(BaseModel):
    """Payload for ``PATCH /v1/support/tickets/{ticket_num}`` — updates ticket state."""

    status: str  # "open" | "in_progress" | "waiting" | "resolved" | "closed"
    resolution: str | None = None  # Mandatory when status is "resolved" or "closed"
    assigned_to: str | None = None
    # The support admin's decision; stored apart from the reporter's choice.
    # Omitted keeps the earlier decision; "" clears it.
    severity: str | None = None  # "low" | "medium" | "high" | "critical"
    category: str | None = None  # "bug" | "feature" | "question" | "incident"


class ChatMessage(BaseModel):
    """A single turn in a support-chat conversation."""

    role: str  # "user" | "assistant" | "system"
    content: str  # Message text


class SupportChatRequest(BaseModel):
    """Payload for ``POST /v1/support/chat`` — multi-turn LLM support conversation."""

    messages: list[ChatMessage]  # Full conversation history (oldest first)


# ---------------------------------------------------------------------------
# Orchestration health analytics (GET /v1/analytics/orchestration_health)
# ---------------------------------------------------------------------------


class OrchestrationHealthWeek(BaseModel):
    """Per-week KPI snapshot for the orchestration health endpoint."""

    week: str  # ISO week label, e.g. "2026-W18"
    qa_needs_work_rate: float  # Fraction of QA decisions marked NEEDS_WORK
    avg_developer_tokens: float  # Mean tokens consumed by Developer agent
    architect_consult_count: int  # Number of ARCHITECT_CONSULTED comments
    task_count: int  # Total QA audit rows in the week
    # Developer turns whose token usage the proxy did not report: left out of
    # avg_developer_tokens rather than averaged in as zero.
    developer_turns_without_tokens: int = 0
    post_batch1: bool  # True when the week falls after 2026-05-02


class OrchestrationHealthSummary(BaseModel):
    """Aggregated pre/post Batch-1 averages."""

    qa_needs_work_rate: float
    avg_developer_tokens: float


class OrchestrationHealthSummaries(BaseModel):
    pre_batch1: OrchestrationHealthSummary
    post_batch1: OrchestrationHealthSummary


class OrchestrationHealthResponse(BaseModel):
    """Response shape for ``GET /v1/analytics/orchestration_health``."""

    anchor_commit: str
    anchor_date: str  # ISO-8601 date of the Batch-1 anchor
    weeks: list[OrchestrationHealthWeek]
    summary: OrchestrationHealthSummaries


class AgentCreateRequest(BaseModel):
    """Payload for POST /v1/agents — create an agent for a company."""

    company_id: int
    name: str = ""
    role: str
    persona: str | None = None
    seniority: str = "Senior"
    specialty: str = ""
    model: str = ""
    system_prompt: str | None = None
    token_budget: int = Field(default=500000, ge=0)


class AgentUpdateRequest(BaseModel):
    """Payload for PATCH /v1/agents/{id} — partial agent update."""

    name: str | None = None
    role: str | None = None
    persona: str | None = None
    seniority: str | None = None
    specialty: str | None = None
    model: str | None = None
    system_prompt: str | None = None
    token_budget: int | None = Field(default=None, ge=0)


class AgentPromptRequest(BaseModel):
    """Payload for POST /v1/agents/generate_prompt — auto-generate a system prompt."""

    role: str
    seniority: str = "Senior"
    specialty: str = ""
    persona: str = ""
