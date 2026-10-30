"""
JetStream names and subjects for the delivery streams, scoped to a deployment.

Streams use work-queue retention: each message goes to exactly one consumer.
Two stacks sharing a broker with the same stream and consumer names therefore
take each other's messages, and the publisher sees work that never completes.
``NATS_NAMESPACE`` (``e2e``, say) keeps them apart.

Namespacing the *names* is not enough. Two work-queue streams bound to the same
*subject* each store every message, so both stacks still process it. The subject
has to differ as well, which is why stream names use ``_`` and subjects use
``.`` — NATS rejects dots in a stream name.

The backend builds the same names (``backend/app/nats_client.py``); keep the two
in step. Empty or whitespace-only values keep the historical names, so a single
stack is unaffected.
"""

import os
import re

DELIVER_SUBJECT = "workspace.deliver"
DELIVERED_SUBJECT = "workspace.delivered"

STREAM_MAX_AGE_SECONDS = 7 * 24 * 3600
STREAM_DUPLICATE_WINDOW_SECONDS = 15 * 60


def _namespace() -> str:
    raw = re.sub(r"[^A-Za-z0-9_-]", "_", os.getenv("NATS_NAMESPACE", "")).strip("_")
    return raw


def scoped(name: str, sep: str = "_") -> str:
    """Prefix *name* with the namespace; *sep* is ``_`` for names, ``.`` for subjects."""
    namespace = _namespace()
    return f"{namespace}{sep}{name}" if namespace else name


# Already scoped: import these, not the bare subjects above.
DELIVERY_SUBJECT = scoped(DELIVER_SUBJECT, ".")
DELIVERY_RESULT_SUBJECT = scoped(DELIVERED_SUBJECT, ".")
DELIVERY_STREAM = scoped("FABRIQUE_DELIVERIES")
DELIVERY_RESULT_STREAM = scoped("FABRIQUE_DELIVERY_RESULTS")
DELIVERY_CONSUMER = scoped("workspace-daemon")

DELIVERY_STREAMS = {
    DELIVERY_STREAM: DELIVERY_SUBJECT,
    DELIVERY_RESULT_STREAM: DELIVERY_RESULT_SUBJECT,
}
