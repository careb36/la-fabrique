"""
Services package — business-logic layer for the Fabrique backend.

Re-exports the public symbols that routers and other consumers need,
keeping import paths short (e.g. ``from services.outbox_service import process_outbox``).
"""

from services.outbox_service import process_outbox

__all__ = ["process_outbox"]
