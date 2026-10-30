import hashlib
import json

from models.agent_run import AgentRun
from schemas import AgentRunCreate
from sqlmodel import Session, select

from services.agent_service import AgentService

MAX_ARTIFACT_SIZE_BYTES = 2 * 1024 * 1024


class ArtifactTooLargeError(ValueError):
    pass


def ingest_agent_run(
    session: Session, payload: AgentRunCreate
) -> tuple[AgentRun, bool]:
    artifact_size = len(payload.artifact.encode("utf-8"))
    if artifact_size > MAX_ARTIFACT_SIZE_BYTES:
        raise ArtifactTooLargeError("artifact exceeds the 2 MiB limit")

    artifact_digest = hashlib.sha256(payload.artifact.encode("utf-8")).hexdigest()
    latest = session.exec(
        select(AgentRun)
        .where(
            AgentRun.company_id == payload.company_id,
            AgentRun.external_ref == payload.external_ref,
        )
        .order_by(AgentRun.version.desc())
    ).first()

    if latest is not None:
        claims_match = json.dumps(latest.claims, sort_keys=True) == json.dumps(
            payload.claims, sort_keys=True
        )
        if latest.artifact_digest == artifact_digest and claims_match:
            return latest, False
        version = latest.version + 1
    else:
        version = 1

    run = AgentRun(
        company_id=payload.company_id,
        external_ref=payload.external_ref,
        version=version,
        producer=payload.producer,
        model=payload.model,
        agent_role=payload.agent_role,
        subject=payload.subject,
        claims=payload.claims,
        artifact_text=payload.artifact,
        artifact_digest=artifact_digest,
        artifact_size=artifact_size,
        started_at=payload.started_at,
        finished_at=payload.finished_at,
    )
    session.add(run)
    session.flush()

    audit_log = AgentService().audit_interaction(
        session=session,
        company_id=run.company_id,
        interaction_id=f"agent-run:{payload.external_ref}",
        agent_id=payload.producer,
        action="agent_run_ingested",
        details={
            "company_id": str(payload.company_id),
            "producer": payload.producer,
            "external_ref": payload.external_ref,
            "version": version,
            "model": payload.model,
        },
        result={
            "agent_run_id": run.id,
            "artifact_digest": artifact_digest,
            "artifact_size": artifact_size,
        },
        decision_signature=None,
        cost_tokens=0,
    )
    run.audit_log_id = audit_log.id
    session.add(run)
    session.commit()
    session.refresh(run)
    return run, True
