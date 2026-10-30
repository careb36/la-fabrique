"""
A hash chain per company over the audit rows.

Each row of a company gets ``chain_seq`` (1, 2, 3… within the company),
``prev_hash`` (the previous row's ``chain_hash``) and ``chain_hash``, computed
over the company id, the sequence number, the previous hash and the digest of
the row's signed fields (``audit_signing.canonical_payload``). A row deleted,
inserted, reordered, altered or moved to another company breaks the chain at
that point, which a per-row signature cannot show.

``chain_hash`` is ``hmac-sha256:<hex>`` when ``AUDIT_SIGNING_KEY`` is set, so
rewriting a keyed stretch needs the key, or ``unsigned:<sha256-hex>`` when it
is not, which still shows accidental damage but not a rewrite by someone who
can write to the database. With a key configured, an unkeyed row after a keyed
one is reported as a ``downgrade``: someone without the key cannot rewrite the
end of a keyed chain as unkeyed and have it pass. What the chain alone cannot
show is a chain rewritten unkeyed from its first row, or its newest rows
dropped; ``verify_chain`` returns the head (last sequence number and hash) so
it can be recorded elsewhere and compared later.

The encoding below is part of the stored format: ``CHAIN_VERSION`` goes into
every hash, and a change to the encoding needs a new version.

Rows without a company (legacy and global rows) are not chained.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import audit_signing
from audit_signing import (
    SIGNED_PREFIX,
    UNSIGNED_PREFIX,
    canonical_payload,
    sign_audit_payload,
)
from sqlalchemy import text
from sqlmodel import Session, select

CHAIN_VERSION = 1
# The advisory-lock namespace for the chain ("audit" in ASCII), with the
# company id as the second key: one writer per company at a time.
_LOCK_NAMESPACE = 0x6175646974 & 0x7FFFFFFF
_MAX_BREAKS_REPORTED = 20


def _row_payload(row: Any) -> bytes:
    return canonical_payload(
        interaction_id=row.interaction_id,
        agent_id=row.agent_id,
        action=row.action,
        details=row.details,
        result=row.result,
        cost_tokens=row.cost_tokens,
        created_at=row.created_at,
    )


def _chain_input(company_id: int, seq: int, prev_hash: str | None, row: Any) -> bytes:
    payload = {
        "v": CHAIN_VERSION,
        "company_id": company_id,
        "seq": seq,
        "prev": prev_hash or "",
        "row": hashlib.sha256(_row_payload(row)).hexdigest(),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def chain_hash(
    company_id: int, seq: int, prev_hash: str | None, row: Any, key: str | None
) -> str:
    """The chain hash of one row, keyed when an audit signing key is configured."""
    data = _chain_input(company_id, seq, prev_hash, row)
    if key is None:
        return f"{UNSIGNED_PREFIX}{hashlib.sha256(data).hexdigest()}"
    return f"{SIGNED_PREFIX}{hmac.new(key.encode('utf-8'), data, hashlib.sha256).hexdigest()}"


def _lock_company_chain(session: Session, company_id: int) -> None:
    """Serialize chain writers for one company on Postgres (no-op elsewhere)."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.exec(
            text("SELECT pg_advisory_xact_lock(:namespace, :company_id)").bindparams(
                namespace=_LOCK_NAMESPACE, company_id=company_id
            )
        )


def seal_audit_row(session: Session, row: Any) -> Any:
    """Sign a new audit row and, for a company's row, append it to that company's chain.

    The row is added and flushed so its stored values are what get signed;
    the caller commits. The unique index on (company_id, chain_seq) refuses a
    second row with the same number if two writers ever race past the lock.
    """
    from models import AuditLog

    session.add(row)
    session.flush()
    session.refresh(row)
    row.decision_signature = sign_audit_payload(_row_payload(row))
    if row.company_id is not None:
        _lock_company_chain(session, row.company_id)
        last = session.exec(
            select(AuditLog)
            .where(AuditLog.company_id == row.company_id)
            .where(AuditLog.chain_seq.is_not(None))  # type: ignore[union-attr]
            .where(AuditLog.id != row.id)
            .order_by(AuditLog.chain_seq.desc())  # type: ignore[union-attr]
            .limit(1)
        ).first()
        seq = (last.chain_seq if last is not None else 0) + 1
        prev = last.chain_hash if last is not None else None
        row.chain_seq = seq
        row.prev_hash = prev
        row.chain_hash = chain_hash(
            row.company_id, seq, prev, row, audit_signing._configured_key()
        )
    session.add(row)
    session.flush()
    return row


def verify_chain(session: Session, company_id: int) -> dict:
    """Walk a company's chain from its first row and report where it breaks.

    ``status`` is ``empty`` (no chained rows), ``intact`` or ``broken``;
    ``mode`` says whether the hashes are keyed (``hmac-sha256``), unkeyed
    (``unsigned``) or both (``mixed``); ``head`` is the last row's sequence
    number and hash; ``breaks`` lists up to twenty problems by sequence
    number: ``gap`` (a number is missing or repeated: a row was deleted,
    inserted or renumbered), ``prev_mismatch`` (the link to the previous row
    does not match), ``hash_mismatch`` (the row or its place was altered) and
    ``key_missing`` (a keyed hash with no key configured to check it) and
    ``downgrade`` (with a key configured, an unkeyed row after a keyed one).
    """
    from models import AuditLog

    rows = session.exec(
        select(AuditLog)
        .where(AuditLog.company_id == company_id)
        .where(AuditLog.chain_seq.is_not(None))  # type: ignore[union-attr]
        .order_by(AuditLog.chain_seq, AuditLog.id)  # type: ignore[arg-type]
    ).all()
    if not rows:
        return {
            "company_id": company_id,
            "status": "empty",
            "mode": None,
            "rows": 0,
            "head": None,
            "breaks": [],
        }

    key = audit_signing._configured_key()
    breaks: list[dict] = []
    modes: set[str] = set()
    expected_seq = 1
    previous_hash: str | None = None
    keyed_seen = False

    def report(seq: int, reason: str) -> None:
        if len(breaks) < _MAX_BREAKS_REPORTED:
            breaks.append({"seq": seq, "reason": reason})

    for row in rows:
        stored = row.chain_hash or ""
        keyed = stored.startswith(SIGNED_PREFIX)
        modes.add("hmac-sha256" if keyed else "unsigned")
        if key is not None and keyed_seen and not keyed:
            report(row.chain_seq, "downgrade")
        keyed_seen = keyed_seen or keyed
        if row.chain_seq != expected_seq:
            report(row.chain_seq, "gap")
        if (row.prev_hash or None) != previous_hash:
            report(row.chain_seq, "prev_mismatch")
        if keyed and key is None:
            report(row.chain_seq, "key_missing")
        else:
            recomputed = chain_hash(
                company_id,
                row.chain_seq,
                row.prev_hash,
                row,
                key if keyed else None,
            )
            if not hmac.compare_digest(stored, recomputed):
                report(row.chain_seq, "hash_mismatch")
        expected_seq = row.chain_seq + 1
        previous_hash = row.chain_hash

    last = rows[-1]
    return {
        "company_id": company_id,
        "status": "broken" if breaks else "intact",
        "mode": modes.pop() if len(modes) == 1 else "mixed",
        "rows": len(rows),
        "head": {"seq": last.chain_seq, "chain_hash": last.chain_hash},
        "breaks": breaks,
    }
