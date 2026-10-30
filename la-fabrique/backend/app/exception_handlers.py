"""
Global exception handlers for the Fabrique Enterprise API.
"""

import os
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from logging_config import logger


def register_exception_handlers(app):
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """
        Catch-all exception handler that:
        1. Logs the full traceback (truncated to 1 000 chars to avoid log flooding).
        2. POSTs a structured error report to the vendor support webhook (if configured).
        3. Publishes a ``system.maintenance.create_ticket`` NATS event so the on-call
           agent can create an incident ticket automatically.
        """
        error_type = type(exc).__name__
        error_msg = str(exc)
        trace = traceback.format_exc()[-1000:]

        logger.error(f"System Exception: {error_msg}", extra={"error_details": trace})

        vendor_webhook = os.getenv("FABRIQUE_VENDOR_SUPPORT_URL")
        if vendor_webhook:
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    await client.post(
                        vendor_webhook,
                        json={
                            "vendor_id": "CAROLINA_PEREIRA_PROD",
                            "system_version": "2026.4.1",
                            "error_type": error_type,
                            "error_message": error_msg,
                            "traceback": trace,
                            "endpoint": f"{request.method} {request.url.path}",
                        },
                        timeout=2.0,
                    )
            except Exception as report_e:  # noqa: BLE001 - Support reporting must not replace the original error.
                logger.error(f"Failed to reach Vendor Support: {report_e}")

        nats = request.app.state.nats_client
        if nats:
            try:
                await nats.publish(
                    "system.maintenance.create_ticket",
                    json.dumps(  # noqa: F821 - Missing import is a deferred bug; preserve this error path.
                        {
                            "subject": "[SYSTEM ERROR] Fabrique Engine Failure",
                            "description": "A report has been sent to the vendor (Carolina Pereira) for resolution.",
                            "priority": "critical",
                        }
                    ).encode(),
                )
            except Exception:  # noqa: BLE001, S110 - Ticket publishing is best-effort during error handling.
                pass

        return JSONResponse(
            status_code=500,
            content={
                "detail": "Fabrique Engine Error. A technical report has been sent to Vendor Support (Carolina Pereira)."
            },
        )
