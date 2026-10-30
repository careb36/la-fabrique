"""
Database connectivity layer for Fabrique Enterprise Backend.

Provides:
- A SQLModel / SQLAlchemy engine connected to PostgreSQL via ``psycopg2``.
- ``create_db_and_tables()`` — idempotent table creation called at startup.
- ``get_session()`` — FastAPI dependency that yields a scoped SQLModel session.
- ``get_neo4j_driver()`` — factory for the Neo4j bolt driver (Temporal Knowledge Graph).

Connection parameters are read from environment variables with safe defaults
for local development.
"""

import os
from collections.abc import Generator

import neo4j
from logging_config import logger
from sqlmodel import Session, SQLModel, create_engine

# ---------------------------------------------------------------------------
# PostgreSQL — SQLModel / SQLAlchemy engine
# ---------------------------------------------------------------------------


def _build_database_url() -> str:
    """Construct the PostgreSQL DSN from individual environment variables."""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "factory")
    password = os.getenv("POSTGRES_PASSWORD", "")
    db = os.getenv("POSTGRES_DB", "factory")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


# Connection pool sized for moderate multi-tenant load:
# - pool_size=5  : permanent connections kept alive.
# - max_overflow=10: temporary connections allowed beyond the pool.
# - pool_pre_ping=True: validates connections before use to catch stale sockets.
def _connect_args(url: str) -> dict[str, str]:
    """Pin a Postgres session to UTC.

    The models write aware UTC datetimes into ``timestamp`` columns and the
    board's comments carry naive UTC text. Postgres converts an aware value
    to the session's zone before dropping it, so a server set to another
    zone would keep the two in different clocks, and every comparison
    between them (a triage against a person's send-back, for one) would be
    off by the offset.
    """
    return {"options": "-c timezone=utc"} if url.startswith("postgresql") else {}


_DATABASE_URL = _build_database_url()
engine = create_engine(
    _DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args(_DATABASE_URL),
)


def _ensure_runtime_schema() -> None:
    """Apply lightweight additive fixes for local databases created by older schemas."""
    statements = (
        # agents — original additive fixes
        "ALTER TABLE IF EXISTS agents ADD COLUMN IF NOT EXISTS name VARCHAR(255) DEFAULT ''",
        "ALTER TABLE IF EXISTS agents ADD COLUMN IF NOT EXISTS model VARCHAR(255) DEFAULT ''",
        "ALTER TABLE IF EXISTS agents ADD COLUMN IF NOT EXISTS system_prompt TEXT",
        "ALTER TABLE IF EXISTS agents ADD COLUMN IF NOT EXISTS token_budget INTEGER DEFAULT 500000",
        # sprints — scope replaces duration_days
        "ALTER TABLE IF EXISTS sprints ADD COLUMN IF NOT EXISTS scope_size VARCHAR DEFAULT 'M'",
        "ALTER TABLE IF EXISTS sprints ALTER COLUMN duration_days DROP NOT NULL",
        # companies — default scope replaces default_sprint_length_days
        "ALTER TABLE IF EXISTS companies ADD COLUMN IF NOT EXISTS default_scope_size VARCHAR DEFAULT 'M'",
        "ALTER TABLE IF EXISTS companies ALTER COLUMN default_sprint_length_days DROP NOT NULL",
        # assistant runtime state — persistent cooldown / quota metadata
        """
        CREATE TABLE IF NOT EXISTS assistant_runtime_state (
            id SERIAL PRIMARY KEY,
            company_id INTEGER NOT NULL REFERENCES companies(id),
            assistant_key VARCHAR(255) NOT NULL,
            cooldown_until TIMESTAMP NULL,
            last_error TEXT NULL,
            updated_at TIMESTAMP NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_assistant_runtime_state_company_id ON assistant_runtime_state (company_id)",
        "CREATE INDEX IF NOT EXISTS ix_assistant_runtime_state_assistant_key ON assistant_runtime_state (assistant_key)",
        # bug_reports — the Support agent's triage beside the reporter's choice
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS agent_reply TEXT",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS suggested_severity VARCHAR(20)",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS suggested_category VARCHAR(50)",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS triaged_by VARCHAR(100)",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS triaged_at TIMESTAMP",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS decided_severity VARCHAR(20)",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS decided_category VARCHAR(50)",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS decided_by VARCHAR(255)",
        "ALTER TABLE IF EXISTS bug_reports ADD COLUMN IF NOT EXISTS decided_at TIMESTAMP",
        # A reporter who chose no severity or category leaves it empty, not a default.
        "ALTER TABLE IF EXISTS bug_reports ALTER COLUMN category DROP NOT NULL",
        "ALTER TABLE IF EXISTS bug_reports ALTER COLUMN category DROP DEFAULT",
        "ALTER TABLE IF EXISTS bug_reports ALTER COLUMN severity DROP NOT NULL",
        "ALTER TABLE IF EXISTS bug_reports ALTER COLUMN severity DROP DEFAULT",
        # agent_runs — the Reviewer agent's suggestion beside a person's approval
        "ALTER TABLE IF EXISTS agent_runs ADD COLUMN IF NOT EXISTS suggested_decision VARCHAR(20)",
        "ALTER TABLE IF EXISTS agent_runs ADD COLUMN IF NOT EXISTS suggested_category VARCHAR(20)",
        "ALTER TABLE IF EXISTS agent_runs ADD COLUMN IF NOT EXISTS suggested_reason TEXT",
        "ALTER TABLE IF EXISTS agent_runs ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(100)",
        "ALTER TABLE IF EXISTS agent_runs ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP",
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id)",
        "CREATE INDEX IF NOT EXISTS ix_audit_log_company_id ON audit_log (company_id)",
        # audit_log — a hash chain per company (audit_chain.py)
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain_seq INTEGER",
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS prev_hash VARCHAR",
        "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS chain_hash VARCHAR",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_log_company_chain_seq ON audit_log (company_id, chain_seq)",
        """
        UPDATE audit_log AS a SET company_id = c.id
        FROM companies AS c
        WHERE a.company_id IS NULL AND a.details->>'company_id' = c.id::text
        """,
    )
    # vector_memory is created by db/init-db/init.sql (it needs pgvector), not
    # by SQLModel, so a database set up without that script has no such table.
    vector_memory_statements = (
        "ALTER TABLE vector_memory ADD COLUMN IF NOT EXISTS company_id INTEGER REFERENCES companies(id)",
        "CREATE INDEX IF NOT EXISTS ix_vector_memory_company_id ON vector_memory (company_id)",
        """
        UPDATE vector_memory AS m SET company_id = c.id
        FROM companies AS c
        WHERE m.company_id IS NULL AND m.metadata->>'company_id' = c.id::text
        """,
    )

    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
        has_vector_memory = connection.exec_driver_sql(
            "SELECT to_regclass('vector_memory') IS NOT NULL"
        ).scalar()
        if has_vector_memory:
            for statement in vector_memory_statements:
                connection.exec_driver_sql(statement)
        else:
            logger.warning(
                "Table vector_memory is missing: memory search and RAG are "
                "unavailable until db/init-db/init.sql is applied to this database."
            )


def create_db_and_tables() -> None:
    """Create all tables defined via SQLModel (idempotent — safe to call on startup)."""
    SQLModel.metadata.create_all(engine)
    _ensure_runtime_schema()


def get_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a SQLModel Session.

    The session is automatically closed when the request completes,
    even if an exception is raised (context-manager behaviour of ``Session``).
    """
    with Session(engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Neo4j driver (unchanged — Neo4j is not managed by SQLModel)
# ---------------------------------------------------------------------------


def get_neo4j_driver() -> neo4j.Driver:
    """
    Return a new Neo4j bolt driver instance.

    Credentials are read from environment variables.  This function creates a
    new driver object each time it is called; callers are responsible for
    closing the driver when they are done.
    """
    return neo4j.GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )


def ensure_memory_graph_schema(driver) -> None:
    """Backfill historical graph ownership without rewriting evidence metadata."""
    from models.company import Company
    from sqlmodel import select

    with Session(engine) as sql_session:
        company_ids = list(sql_session.exec(select(Company.id)).all())
    with driver.session() as session:
        session.run(
            """
            MATCH (e)
            WHERE any(label IN labels(e) WHERE label STARTS WITH 'Episodic_')
            SET e:Episodic
            """
        ).consume()
        session.run(
            """
            MATCH (e)
            WHERE (e:Memory OR any(label IN labels(e) WHERE label STARTS WITH 'Episodic'))
              AND e.company_id IS NULL AND e.metadata IS NOT NULL
            WITH e, toInteger(apoc.convert.fromJsonMap(e.metadata).company_id) AS company_id
            WHERE company_id IN $company_ids
            SET e.company_id = company_id
            """,
            company_ids=company_ids,
        ).consume()
        session.run(
            "CREATE INDEX episodic_company_id IF NOT EXISTS FOR (e:Episodic) ON (e.company_id)"
        ).consume()
