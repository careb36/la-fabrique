"""Run the verifier against deliveries that lie, and print what it caught.

    cd backend && PYTHONPATH=.:app python -m eval.verificador.run

The number this prints is the product's central claim, measured instead of
asserted: of N deliveries whose claims the evidence contradicts or cannot
support, the verifier believed none of them — and it still believed the honest
delivery it was given as a control.

Every case goes through ``services.verification.verify_agent_run`` against an
in-memory SQLite session, so the audit write and the stored ``Verification`` are
exercised too. No model is called and no network is used, so the run is
deterministic and takes a second.
"""

from __future__ import annotations

import os
import sys
import tempfile

# The verifier writes one audit row per run; give it a scratch directory before
# any service reads the setting, so the benchmark runs from a bare checkout.
if not os.environ.get("AUDIT_LOG_PATH"):
    os.environ["AUDIT_LOG_PATH"] = tempfile.mkdtemp(prefix="verificador-audit-")

from models.agent_run import AgentRun, AgentRunApproval, Verification
from models.audit import AuditLog
from models.company import Agent, BusinessUnit, Company, CompanyMember, User
from services.verification import verify_agent_run
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from eval.verificador.cases import CASES, Case

_TABLES = [
    Company.__table__,
    User.__table__,
    CompanyMember.__table__,
    BusinessUnit.__table__,
    Agent.__table__,
    AuditLog.__table__,
    AgentRun.__table__,
    AgentRunApproval.__table__,
    Verification.__table__,
]


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=_TABLES)
    return engine


def _run_case(session: Session, company_id: int, case: Case):
    run = AgentRun(
        company_id=company_id,
        external_ref=f"bench:{case.name}",
        producer="benchmark",
        claims=case.claims,
        artifact_text=case.artifact_text,
        artifact_digest="0" * 64,
        artifact_size=case.artifact_size,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return verify_agent_run(session, run, case.evidence)


def _tier(verification: Verification) -> str | None:
    for check in verification.checks or []:
        if check.get("name") == "risk_tier":
            return check.get("tier")
    return None


def main() -> int:
    engine = _engine()
    failures: list[str] = []
    believed: list[str] = []
    lies = [case for case in CASES if case.refuses_to_believe]

    with Session(engine) as session:
        company = Company(company_name="Verifier benchmark")
        session.add(company)
        session.commit()
        session.refresh(company)

        print(f"{'case':<52} {'verdict':<14} expected")
        print("-" * 84)
        for case in CASES:
            verification = _run_case(session, company.id, case)
            verdict = verification.verdict
            ok = verdict in case.accepted
            if case.expect_tier is not None and _tier(verification) != case.expect_tier:
                ok = False
                verdict = f"{verdict} (tier={_tier(verification)})"
            print(
                f"{case.name:<52} {verdict:<14} "
                f"{'/'.join(case.accepted)}  {'ok' if ok else 'FAIL'}"
            )
            if not ok:
                failures.append(case.name)
                for check in verification.checks or []:
                    print(
                        f"    {check['name']}: {check['outcome']} — {check['observation']}"
                    )
            # Believed means a run the evidence contradicts, or cannot support,
            # came back verified. A case whose whole point is the risk tier
            # reaches verified legitimately, so its own expectation decides.
            if (
                case.refuses_to_believe
                and verification.verdict == "verified"
                and "verified" not in case.accepted
            ):
                believed.append(case.name)

        stored = len(session.exec(select(Verification)).all())

    print("-" * 84)
    print(f"lies not believed:  {len(lies) - len(believed)}/{len(lies)}")
    print(f"cases as specified: {len(CASES) - len(failures)}/{len(CASES)}")
    print(f"stored:             {stored} verification(s), one audit row each")

    if believed:
        print(f"\nBELIEVED A LIE: {', '.join(believed)}", file=sys.stderr)
    if failures:
        print(f"\nFAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nall cases behaved as specified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
