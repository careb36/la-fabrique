"""
AgentService — orchestration layer for LangGraph workflow triggers and audit logging.

Responsibilities:
- Publish ``workspace.generate`` events to NATS so the LangGraph runtime can
  pick them up asynchronously (fire-and-forget pattern).
- Write dual-destination audit entries: filesystem JSONL + ``audit_log`` table.

This service is intentionally thin; it delegates heavy lifting to the NATS
event bus and the LangGraph agents.
"""

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from audit_chain import seal_audit_row
from models import AuditLog
from sqlmodel import Session

logger = logging.getLogger("fabrique-backend")


class AgentService:
    """
    Service layer for agent workflow orchestration and audit trail management.

    Args:
        nats_client: An active ``NATSClient`` instance used for publishing
                     events.  May be ``None`` in unit-test contexts where NATS
                     is not available.
    """

    def __init__(self, nats_client=None):
        self.nats_client = nats_client

    async def generate_package(
        self,
        company_id: int,
        story: str,
        constraints: str,
        business_unit_id: int | None = None,
        interaction_id: str | None = None,
        session: Session = None,
    ) -> str:
        """
        Trigger an AI package generation workflow by publishing to NATS.
        """
        if not self.nats_client:
            raise RuntimeError("NATS client not initialized")

        # Resolve Business Unit for Governance (Phase 4)
        if not business_unit_id:
            if not session:
                raise ValueError("Session required to resolve default Business Unit")

            from models.company import BusinessUnit
            from sqlmodel import select

            unit = session.exec(
                select(BusinessUnit).where(BusinessUnit.company_id == company_id)
            ).first()
            if not unit:
                raise ValueError(
                    f"No Business Unit found for company {company_id}. Governance requires a cost centre."
                )
            business_unit_id = unit.id

        interaction_id = interaction_id or str(uuid4())
        await self.nats_client.publish(
            "workspace.generate",
            {
                "interaction_id": interaction_id,
                "company_id": company_id,
                "business_unit_id": business_unit_id,
                "story": story,
                "constraints": constraints,
            },
        )
        return interaction_id

    def audit_interaction(
        self,
        session: Session,
        interaction_id: str,
        agent_id: int,
        action: str,
        details: str,
        result: str,
        decision_signature: str,
        cost_tokens: int,
        company_id: int | None = None,
    ):
        """
        Write a dual-destination audit entry for an agent interaction.

        Destinations:
        1. **Filesystem** — appends a JSON line to ``AUDIT_LOG_PATH/audit.jsonl``
           once the row is committed, an append-only copy of the trail outside
           the database.
        2. **Database** — inserts an ``AuditLog`` row in the same SQLModel session.
           Provides queryable history for governance dashboards.

        Args:
            session:            Active SQLModel session; the caller is responsible
                                for committing.
            interaction_id:     UUID correlating all audit entries for a workflow run.
            agent_id:           Identifier of the agent that performed the action.
            action:             Short label (e.g. ``"generate_code"``).
            details:            Arbitrary context dict / string for the action.
            result:             Outcome dict / string returned by the action.
            decision_signature: Deprecated caller value; ignored in favor of a server signature.
            cost_tokens:        LLM tokens consumed; credited to the business unit.

        Returns:
            The persisted ``AuditLog`` ORM instance.
        """
        if decision_signature is not None:
            logger.warning(
                "decision_signature supplied by caller is ignored; signatures are computed server-side"
            )

        now = datetime.now(UTC).replace(tzinfo=None)
        log = AuditLog(
            company_id=company_id,
            interaction_id=interaction_id,
            agent_id=agent_id,
            action=action,
            details=details,
            result=result,
            cost_tokens=cost_tokens,
            created_at=now,
        )
        # Signed, and appended to the company's hash chain (audit_chain.py).
        seal_audit_row(session, log)
        signature = log.decision_signature

        entry = {
            "company_id": log.company_id,
            "timestamp": log.created_at.isoformat(),
            "interaction_id": log.interaction_id,
            "agent_id": log.agent_id,
            "action": log.action,
            "details": log.details,
            "result": log.result,
            "decision_signature": signature,
            "cost_tokens": log.cost_tokens,
            "chain_seq": log.chain_seq,
            "prev_hash": log.prev_hash,
            "chain_hash": log.chain_hash,
        }

        # Database audit — queryable via the governance dashboard.
        session.commit()

        # Filesystem audit — append-only JSONL; one JSON object per line.
        # Written after the commit, so the file never holds a chain entry the
        # database rolled back (its sequence number would be given out again).
        audit_log_path = Path(os.getenv("AUDIT_LOG_PATH", "/app/.factory/logs"))
        audit_log_path.mkdir(parents=True, exist_ok=True)
        with open(audit_log_path / "audit.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
        return log
