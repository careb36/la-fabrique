"""
Signing and verification for audit-log rows.

Canonical payload bytes are UTF-8 encoding of ``json.dumps`` over the
``interaction_id``, ``agent_id``, ``action``, ``details``, ``result``,
``cost_tokens``, and ``created_at.isoformat()`` fields, using
``sort_keys=True``, ``separators=(",", ":")``, ``ensure_ascii=False``, and
``default=str``. This encoding is part of the stored signature format and
must not change without an explicit signature-versioning strategy.

Rows are stored as ``hmac-sha256:<hex>`` when ``AUDIT_SIGNING_KEY`` is set,
or ``unsigned:<sha256-hex>`` when it is not. Unrecognised or absent prefixes
are legacy signatures and are never treated as valid.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("fabrique-backend")

SIGNED_PREFIX = "hmac-sha256:"
UNSIGNED_PREFIX = "unsigned:"

_missing_key_warned = False


def _configured_key() -> str | None:
    """Return the configured audit signing key, or None when unset or blank."""
    from config import settings

    key = getattr(settings, "AUDIT_SIGNING_KEY", None)
    if key is None:
        return None
    key = key.strip()
    return key or None


def canonical_payload(
    *,
    interaction_id: Any,
    agent_id: Any,
    action: Any,
    details: Any,
    result: Any,
    cost_tokens: Any,
    created_at: datetime,
) -> bytes:
    """Serialize the signed audit fields using the pinned canonical format."""
    payload = {
        "interaction_id": interaction_id,
        "agent_id": agent_id,
        "action": action,
        "details": details,
        "result": result,
        "cost_tokens": cost_tokens,
        "created_at": created_at.isoformat(),
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


def sign_audit_payload(payload: bytes) -> str:
    """Sign payload bytes with HMAC-SHA256, or mark their digest unsigned."""
    global _missing_key_warned

    key = _configured_key()
    if key is None:
        if not _missing_key_warned:
            _missing_key_warned = True
            logger.warning(
                "AUDIT_SIGNING_KEY is not configured. Audit rows are being "
                "stored with an 'unsigned:' prefix; configure a key to sign them."
            )
        digest = hashlib.sha256(payload).hexdigest()
        return f"{UNSIGNED_PREFIX}{digest}"

    digest = hmac.new(key.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{SIGNED_PREFIX}{digest}"


def is_signing_enabled() -> bool:
    """Return whether an audit signing key is configured."""
    return _configured_key() is not None


def verify_audit_row(row) -> dict:
    """Return the verification status and signature mode for an audit row."""
    signature = getattr(row, "decision_signature", None)
    if not isinstance(signature, str):
        return {"status": "legacy", "mode": "legacy"}

    if signature.startswith(SIGNED_PREFIX):
        mode = "hmac-sha256"
        key = _configured_key()
        if key is None:
            return {"status": "invalid", "mode": mode}
        expected = hmac.new(
            key.encode("utf-8"),
            canonical_payload(
                interaction_id=row.interaction_id,
                agent_id=row.agent_id,
                action=row.action,
                details=row.details,
                result=row.result,
                cost_tokens=row.cost_tokens,
                created_at=row.created_at,
            ),
            hashlib.sha256,
        ).hexdigest()
        valid = hmac.compare_digest(signature[len(SIGNED_PREFIX) :], expected)
        return {"status": "valid" if valid else "invalid", "mode": mode}

    if signature.startswith(UNSIGNED_PREFIX):
        expected = hashlib.sha256(
            canonical_payload(
                interaction_id=row.interaction_id,
                agent_id=row.agent_id,
                action=row.action,
                details=row.details,
                result=row.result,
                cost_tokens=row.cost_tokens,
                created_at=row.created_at,
            )
        ).hexdigest()
        valid = hmac.compare_digest(signature[len(UNSIGNED_PREFIX) :], expected)
        return {"status": "unsigned" if valid else "invalid", "mode": "unsigned"}

    return {"status": "legacy", "mode": "legacy"}
