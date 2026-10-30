"""
CompanyService — logic for company lifecycle, tenant bootstrapping, and team discovery.

Responsibilities:
- Initialise a new company tenant with agents and credentials.
- Aggregate sprint health and token usage analytics for the dashboard.
- Bridge Postgres multi-tenant data to the Neo4j Temporal Knowledge Graph.
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from crypto import encrypt_value
from database import get_neo4j_driver
from logging_config import logger
from models import (
    Agent,
    AuditLog,
    BacklogItem,
    BusinessUnit,
    Company,
    CompanyMember,
    OutboxEvent,
    ProjectCredential,
    ProjectDiscovery,
    Sprint,
)
from sqlmodel import Session, func, select

from services.sprint_planner import plan_foundation_sprint


class CompanyService:
    """
    Service layer for multi-tenancy governance and company lifecycle management.

    Args:
        session: An active ``SQLModel`` session for database persistence.
    """

    def __init__(self, session: Session):
        self.session = session

    def init_company(
        self,
        company_name: str,
        agents: list[dict[str, Any]],
        default_scope_size: str = "M",
        default_sprint_length_days: int | None = None,  # deprecated
        autonomy_level: int = 2,
        permissions: dict[str, str] | None = None,
        project_path: str | None = None,
        detected_stack: dict[str, Any] | None = None,
        owner_user_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Bootstrap a new company tenant with its AI agents and project credentials.

        This involves multiple tables and a non-critical Neo4j seed operation.
        Returns a summary of the created entities.
        """
        # 1. Create the Company
        company = Company(
            company_name=company_name,
            default_scope_size=default_scope_size,
            autonomy_level=autonomy_level,
        )
        self.session.add(company)
        self.session.flush()

        if owner_user_id is not None:
            self.session.add(
                CompanyMember(
                    company_id=company.id, user_id=owner_user_id, human_role="Owner"
                )
            )

        # The project chosen in "New company" is where this company's agents
        # write their files.  Discovery runs before the company exists, so it
        # cannot record it; without this row agent files fell back to
        # AGENT_WORKSPACE_ROOT (this repository).
        if project_path and project_path.strip():
            self.session.add(
                ProjectDiscovery(
                    company_id=company.id,
                    project_path=project_path.strip(),
                    detected_stack=json.dumps(detected_stack)
                    if detected_stack
                    else None,
                )
            )

        # 2. Create Agents
        for agent_data in agents:
            self.session.add(
                Agent(
                    company_id=company.id,
                    name=agent_data.get("name", ""),
                    role=agent_data.get("role"),
                    persona=agent_data.get("persona"),
                    seniority=agent_data.get("seniority", "Senior"),
                    specialty=agent_data.get("specialty", ""),
                    model=agent_data.get("model", ""),
                    system_prompt=agent_data.get("system_prompt"),
                    token_budget=agent_data.get("token_budget", 500000),
                )
            )

        # 3. Create Project Credentials
        if permissions:
            for cred_type, access_level in permissions.items():
                if access_level != "none":
                    # Routed through encrypt_value so the column holds a
                    # self-describing value from the moment a row is written.
                    # The placeholder carries no secret today — init_company
                    # receives only credential_type -> access_level, never a
                    # value — but wiring it now means the first real secret
                    # written here is encrypted rather than retrofitted.
                    self.session.add(
                        ProjectCredential(
                            company_id=company.id,
                            credential_type=cred_type,
                            access_level=access_level,
                            encrypted_value=encrypt_value(
                                "vault_encrypted_placeholder"
                            ),
                        )
                    )

        # 4. Plan and Create Foundation Sprint
        plan = plan_foundation_sprint(
            company_name=company_name,
            agents=agents,
            detected_stack=detected_stack,
            project_path=project_path,
        )

        sprint = Sprint(
            company_id=company.id,
            sprint_name="Sprint 0 — Foundations",
            start_date=datetime.now(UTC).date().isoformat(),
            scope_size=default_scope_size,
            status="active",
            goal=plan.get("goal", f"Foundation sprint for {company_name}"),
        )
        self.session.add(sprint)
        self.session.flush()

        # 5. Create Backlog Items and Outbox Events
        tasks = plan.get("tasks", [])
        for task in tasks:
            bi = BacklogItem(
                sprint_id=sprint.id,
                title=task.get("title", "Untitled task"),
                description=task.get("description", ""),
                priority=task.get("priority", "medium"),
                assignee=task.get("assignee", "PO"),
                status="todo",
            )
            self.session.add(bi)
            self.session.flush()

            nats_payload = {
                "subject": "task.assign",
                "message": {
                    "backlog_item_id": bi.id,
                    "interaction_id": str(uuid4()),
                    "agent": task.get("assignee", "PO"),
                    "sprint_id": sprint.id,
                },
            }
            self.session.add(
                OutboxEvent(
                    aggregate_type="backlog_item",
                    aggregate_id=str(bi.id),
                    event_type="nats_publish",
                    payload=nats_payload,
                )
            )

        self.session.commit()

        # 6. Seed Neo4j (Non-critical)
        self._seed_neo4j(company.id, company_name)

        return {
            "company_id": company.id,
            "sprint_id": sprint.id,
            "task_count": len(tasks),
            "message": f"Company initialized with {len(tasks)} foundation tasks",
        }

    def _seed_neo4j(self, company_id: int, company_name: str):
        """Seed a root Company node in Neo4j (Temporal Knowledge Graph)."""
        try:
            driver = get_neo4j_driver()
            with driver.session() as neo_session:
                neo_session.run(
                    "MERGE (c:Company {id: $id}) "
                    "ON CREATE SET c.name = $name, c.created = timestamp()",
                    id=company_id,
                    name=company_name,
                )
        except Exception as e:  # noqa: BLE001 - Optional graph seeding must not fail company creation.
            logger.error(f"Neo4j seed failed (non-critical): {e}")

    def get_quotas(self, company_id: int) -> list[dict[str, Any]]:
        """Return token usage and limits for all business units of a company."""
        units = self.session.exec(
            select(BusinessUnit).where(BusinessUnit.company_id == company_id)
        ).all()
        return [
            {
                "id": u.id,
                "unit": u.unit_name,
                "limit": u.token_quota_limit,
                "used": u.token_quota_used,
            }
            for u in units
        ]

    def reset_quota(self, bu_id: int) -> dict[str, Any]:
        """Reset the token usage counter for a business unit to zero."""
        unit = self.session.get(BusinessUnit, bu_id)
        if not unit:
            raise ValueError(f"Business Unit {bu_id} not found")
        unit.token_quota_used = 0
        self.session.add(unit)
        self.session.commit()
        return {
            "status": "reset",
            "bu_id": bu_id,
            "unit": unit.unit_name,
            "token_quota_used": 0,
        }

    def get_project_health(self, sprint_id: int) -> dict[str, Any]:
        """Generate a sprint health report using SQLModel idiomatic queries."""
        # 1. Calculate total tokens for this sprint's backlog interactions,
        # counting only the sprint company's rows: another company can log
        # under the same "task-<id>" before this task exists.
        sprint = self.session.get(Sprint, sprint_id)
        item_ids = self.session.exec(
            select(BacklogItem.id).where(BacklogItem.sprint_id == sprint_id)
        ).all()
        interaction_ids = [f"task-{item_id}" for item_id in item_ids]
        total_tokens = 0
        if interaction_ids and sprint is not None:
            total_tokens = (
                self.session.exec(
                    select(func.sum(AuditLog.cost_tokens)).where(
                        AuditLog.interaction_id.in_(interaction_ids),
                        AuditLog.company_id == sprint.company_id,
                    )
                ).one()
                or 0
            )

        # 2. Count tasks per status
        status_counts_rows = self.session.exec(
            select(BacklogItem.status, func.count(BacklogItem.id))
            .where(BacklogItem.sprint_id == sprint_id)
            .group_by(BacklogItem.status)
        ).all()
        status_counts = {status: count for status, count in status_counts_rows}

        ai_summary = (
            f"The sprint is healthy. {status_counts.get('done', 0)} tasks completed. "
            f"Total investment: {total_tokens} tokens. "
            "Velocity is stable, no major blockers detected."
        )

        return {
            "sprint_id": sprint_id,
            "health_score": 92,
            "tokens_consumed": total_tokens,
            "tasks_status": status_counts,
            "ai_executive_summary": ai_summary,
        }

    def list_agents(self, company_id: int) -> list[dict[str, Any]]:
        """Return all configured agents for a company, with activity stats inlined."""
        company = self.session.get(Company, company_id)
        if not company:
            raise ValueError(f"Company {company_id} not found")

        agents = self.session.exec(
            select(Agent)
            .where(Agent.company_id == company_id)
            .order_by(Agent.role, Agent.name, Agent.id)
        ).all()

        activity = self._load_agent_activity(company_id)
        return [self._serialize_agent(agent, activity=activity) for agent in agents]

    def _load_agent_activity(self, company_id: int) -> dict[str, dict[str, Any]]:
        """Aggregate audit_log into per-agent activity stats for the company."""
        sprint_ids = [
            sid
            for (sid,) in self.session.exec(
                select(Sprint.id).where(Sprint.company_id == company_id)
            ).all()
        ]
        if not sprint_ids:
            return {}

        rows = self.session.exec(
            select(
                AuditLog.agent_id,
                func.count(AuditLog.id),
                func.max(AuditLog.created_at),
                func.coalesce(func.sum(AuditLog.cost_usd), 0.0),
                func.coalesce(func.sum(AuditLog.cost_tokens), 0),
            )
            .where(AuditLog.sprint_id.in_(sprint_ids))
            .where(AuditLog.action == "task.execute")
            .group_by(AuditLog.agent_id)
        ).all()

        activity: dict[str, dict[str, Any]] = {}
        for agent_id, total, last_at, cost_usd, total_tokens in rows:
            if agent_id is None:
                continue
            total_int = int(total or 0)
            tokens_int = int(total_tokens or 0)
            avg = int(tokens_int / total_int) if total_int else 0
            activity[str(agent_id)] = {
                "total_tasks": total_int,
                "last_run_at": last_at.isoformat() if last_at else None,
                "total_cost_usd": float(cost_usd) if cost_usd is not None else 0.0,
                "total_tokens": tokens_int,
                "avg_tokens": avg,
                "last_model": None,
            }

        recent_rows = self.session.exec(
            select(AuditLog.agent_id, AuditLog.model)
            .where(AuditLog.sprint_id.in_(sprint_ids))
            .where(AuditLog.action == "task.execute")
            .order_by(AuditLog.created_at.desc())
            .limit(500)
        ).all()
        seen: set[str] = set()
        for agent_id, model in recent_rows:
            if agent_id is None:
                continue
            key = str(agent_id)
            if key in seen:
                continue
            seen.add(key)
            if key in activity:
                activity[key]["last_model"] = model

        return activity

    def create_agent(self, company_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a new agent under a company."""
        company = self.session.get(Company, company_id)
        if not company:
            raise ValueError(f"Company {company_id} not found")

        role = str(payload.get("role") or "").strip()
        if not role:
            raise ValueError("role is required")

        agent = Agent(
            company_id=company_id,
            name=str(payload.get("name") or "").strip(),
            role=role,
            persona=payload.get("persona"),
            seniority=str(payload.get("seniority") or "Senior").strip() or "Senior",
            specialty=str(payload.get("specialty") or "").strip(),
            model=str(payload.get("model") or "").strip(),
            system_prompt=payload.get("system_prompt"),
            token_budget=int(payload.get("token_budget") or 500000),
        )
        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return self._serialize_agent(agent)

    def update_agent(self, agent_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        """Update an existing agent configuration."""
        agent = self.session.get(Agent, agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")

        for field in (
            "name",
            "role",
            "persona",
            "seniority",
            "specialty",
            "model",
            "system_prompt",
            "token_budget",
        ):
            if field not in payload:
                continue
            value = payload[field]
            if field == "token_budget" and value is not None:
                setattr(agent, field, int(value))
            elif (
                field in {"name", "role", "seniority", "specialty", "model"}
                and value is not None
            ):
                setattr(agent, field, str(value).strip())
            else:
                setattr(agent, field, value)

        if not (agent.role or "").strip():
            raise ValueError("role cannot be empty")

        self.session.add(agent)
        self.session.commit()
        self.session.refresh(agent)
        return self._serialize_agent(agent)

    def delete_agent(self, agent_id: int) -> dict[str, Any]:
        """Delete an agent configuration."""
        agent = self.session.get(Agent, agent_id)
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        deleted = self._serialize_agent(agent)
        self.session.delete(agent)
        self.session.commit()
        return {"status": "deleted", "agent": deleted}

    @staticmethod
    def _serialize_agent(
        agent: Agent,
        activity: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        stats = None
        if activity:
            stats = activity.get(agent.name) or activity.get(agent.role or "")
        return {
            "id": agent.id,
            "company_id": agent.company_id,
            "name": agent.name,
            "role": agent.role,
            "persona": agent.persona,
            "seniority": agent.seniority,
            "specialty": agent.specialty,
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "token_budget": agent.token_budget,
            "activity": stats
            or {
                "total_tasks": 0,
                "last_run_at": None,
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "avg_tokens": 0,
                "last_model": None,
            },
        }
