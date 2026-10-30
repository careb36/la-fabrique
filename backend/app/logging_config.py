"""
Structured JSON logging configuration for Fabrique Enterprise Backend.

Exports:
- ``JSONFormatter`` — logging.Formatter subclass that serialises log records
  as JSON objects, making them machine-parseable by log aggregators (e.g.
  Loki, Datadog, CloudWatch).
- ``setup_logger(name)`` — creates (or retrieves) a named logger with a
  JSONFormatter handler attached to stdout.
- ``logger`` — module-level default logger (name ``"fabrique"``).

Optional enrichment: attach ``interaction_id`` to a ``LogRecord`` via
``logger.info("msg", extra={"interaction_id": "..."})`` to correlate log
lines across a single LangGraph workflow run.
"""

import json
import logging
import sys
from datetime import UTC, datetime


class JSONFormatter(logging.Formatter):
    """
    Logging formatter that serialises each record to a single JSON line.

    Emitted fields:
    - ``timestamp``: UTC ISO-8601 string.
    - ``level``: log level name (INFO, WARNING, ERROR, …).
    - ``message``: rendered log message.
    - ``module``: Python module that emitted the record.
    - ``func``: function / method name.
    - ``interaction_id`` (optional): present when the caller passes it via
      ``extra={"interaction_id": "..."}``.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
        }
        # Attach interaction_id when available for distributed tracing.
        if hasattr(record, "interaction_id"):
            log_entry["interaction_id"] = record.interaction_id
        return json.dumps(log_entry)


def setup_logger(name: str = "fabrique") -> logging.Logger:
    """
    Return a named logger configured with ``JSONFormatter`` on stdout.

    The function is idempotent: if the logger already has handlers attached
    (e.g. the module was imported twice), no duplicate handler is added.

    Args:
        name: Logger name; defaults to ``"fabrique"``.

    Returns:
        Configured ``logging.Logger`` instance.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    return logger


# Default logger shared across the backend application.
logger = setup_logger()
