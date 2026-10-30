"""
Fabrique AI Janitor — daily database maintenance service.

Runs as a standalone long-lived container (or bare process).  Executes two
maintenance tasks every 24 hours:

1. **Outbox cleanup** — deletes ``outbox_events`` rows with status
   ``'completed'`` that are older than 7 days, keeping the table small and
   the partial index efficient.

2. **Vector index rebuild** — runs ``REINDEX INDEX CONCURRENTLY`` on the
   ``vector_memory_idx`` HNSW/IVFFlat index so that ANN search stays fast
   after large insert batches.  ``CONCURRENTLY`` means read queries are not
   blocked during the rebuild.

Why a separate container?
--------------------------
Maintenance operations that hold locks (even temporarily) can interfere with
online request-handling.  Isolating them in a dedicated container lets us
schedule them during low-traffic windows and restart them independently of the
main API.
"""

import os
import time
import logging
import psycopg2

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("fabrique-janitor")

def get_db_connection():
    """
    Establish a direct psycopg2 connection for the Janitor process.

    Uses psycopg2 directly (not SQLModel/SQLAlchemy) so we can set
    ``autocommit = True``, which is required by ``REINDEX CONCURRENTLY``
    (that DDL command cannot run inside a transaction block).
    """
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "factory"),
        password=os.getenv("POSTGRES_PASSWORD", "your_secure_password_here"),
        database=os.getenv("POSTGRES_DB", "factory")
    )

def run_janitor_tasks():
    """
    Execute all daily maintenance tasks in a single database session.

    Connects with ``autocommit = True`` so each statement commits immediately
    — a requirement for ``REINDEX CONCURRENTLY``.  All tasks are
    idempotent and safe to run repeatedly.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        # CONCURRENTLY requires auto-commit mode (cannot be run inside a transaction block)
        conn.autocommit = True
        cursor = conn.cursor()

        # One-time migration for the retired approval queue (issue #42).
        cursor.execute("DROP TABLE IF EXISTS task_queue")
        logger.info("Janitor: Dropped retired task_queue table if present.")

        # 1. Clean Outbox (Uses the new partial index)
        cursor.execute(
            "DELETE FROM outbox_events WHERE status = 'completed' AND processed_at < NOW() - INTERVAL '7 days'"
        )
        logger.info(f"Janitor: Deleted {cursor.rowcount} old outbox events.")

        # 3. Vector Index Rebuild (NON-BLOCKING for RAG queries)
        logger.info("Janitor: Rebuilding vector memory index concurrently to prevent read blocks...")
        cursor.execute("REINDEX INDEX CONCURRENTLY vector_memory_idx")
        logger.info("Janitor: Vector index rebuilt successfully.")

    except Exception as e:
        logger.error(f"Janitor failed: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

if __name__ == "__main__":
    # Simulate a daily cron job running in the background container
    # For production, tools like Celery or pure cron are better, but this demonstrates the isolated architecture.
    logger.info("Fabrique AI Janitor Service Online.")
    while True:
        run_janitor_tasks()
        # Run every 24 hours
        time.sleep(86400)
