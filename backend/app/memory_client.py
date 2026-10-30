"""
MemoryClient — dual-store memory abstraction for pgvector and Neo4j.

Provides a unified interface for:
- **Vector memory** (Postgres + pgvector): Stores arbitrary text with dense
  vector embeddings for semantic similarity search.
- **Graph memory** (Neo4j): Stores entities, relationships, and episodic
  Engram nodes for structured knowledge retrieval.

The ``embed()`` call is delegated to ``LLMProxyClient`` (Gemini
``text-embedding-004``) so this module has no direct dependency on any LLM SDK.
"""

import json
from typing import Any

from database import engine, get_neo4j_driver
from sqlmodel import Session, text


class MemoryClient:
    """
    Unified client for Postgres/pgvector and Neo4j memory operations.

    Args:
        neo4j_driver: An initialised ``neo4j.Driver`` instance.  If ``None``,
                      the driver is obtained from ``database.get_neo4j_driver()``.
    """

    def __init__(self, neo4j_driver=None):
        self.engine = engine
        self.neo4j_driver = neo4j_driver or get_neo4j_driver()

    def store(
        self,
        content: str,
        metadata: dict | None = None,
        *,
        company_id: int | None = None,
    ):
        """
        Persist content to both pgvector (semantic search) and Neo4j (graph).

        Workflow:
        1. Embed the content via the LLM proxy.
        2. Insert the vector into the ``vector_memory`` Postgres table.
        3. Create a ``Memory`` node in Neo4j with a ``created`` timestamp.

        If embedding fails (proxy unavailable), the pgvector insert is skipped
        but the Neo4j node is still written.

        Args:
            content:  Raw text to store.
            metadata: Arbitrary key-value metadata persisted as JSONB / JSON.
        """
        from llm_proxy_client import LLMProxyClient

        client = LLMProxyClient()
        embedding = client.embed(content)

        if embedding:
            # Store vector representation for ANN similarity search.
            with Session(self.engine) as session:
                session.execute(
                    text(
                        """
                        INSERT INTO vector_memory (content, embedding, metadata, company_id)
                        VALUES (:content, :embedding, :metadata, :company_id)
                        """
                    ),
                    {
                        "content": content,
                        "company_id": company_id,
                        "embedding": json.dumps(embedding),
                        "metadata": json.dumps(metadata or {}),
                    },
                )
                session.commit()

        # Always write the raw content to Neo4j for graph traversal.
        with self.neo4j_driver.session() as neo_session:
            neo_session.run(
                """
                CREATE (m:Memory {
                    content: $content,
                    company_id: $company_id,
                    metadata: $metadata,
                    created: timestamp()
                })
                """,
                content=content,
                company_id=company_id,
                metadata=json.dumps(metadata or {}),
            )

    def search_similar(
        self,
        query: str,
        limit: int = 10,
        *,
        company_ids: list[int] | None = None,
        include_legacy: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Find semantically similar content using pgvector ANN search.

        Embeds *query*, then ranks stored vectors by cosine distance
        (``<=>`` operator).  Returns results ordered by descending similarity.

        Args:
            query: Natural-language search query.
            limit: Maximum number of results to return.

        Returns:
            List of dicts with keys ``content``, ``metadata``, ``similarity``
            (float in [0, 1] where 1 = identical).
        """
        from llm_proxy_client import LLMProxyClient

        client = LLMProxyClient()
        embedding = client.embed(query)

        if not embedding:
            return []

        company_filter = ""
        params = {"embedding": json.dumps(embedding), "limit": limit}
        if company_ids is not None:
            company_filter = "WHERE (company_id = ANY(:company_ids)"
            if include_legacy:
                company_filter += " OR company_id IS NULL"
            company_filter += ")"
            params["company_ids"] = company_ids

        with Session(self.engine) as session:
            # Cast the parameter to vector so pgvector accepts it.
            results_proxy = session.execute(
                text(
                    f"""
                    SELECT content, metadata, 1 - (embedding <=> CAST(:embedding AS vector)) as similarity, company_id
                    FROM vector_memory
                    {company_filter}
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                params,
            )

            results = []
            for row in results_proxy:
                results.append(
                    {
                        "content": row[0],
                        "metadata": row[1]
                        if isinstance(row[1], dict)
                        else json.loads(row[1] or "{}"),
                        "similarity": row[2],
                        "company_id": row[3],
                        "legacy": row[3] is None,
                    }
                )
            return results

    def store_entity(self, entity_type: str, properties: dict[str, Any]):
        """
        Create a labelled node in Neo4j.

        Args:
            entity_type: Cypher label for the new node (e.g. ``"User"``, ``"Sprint"``).
            properties:  Dict of node properties.
        """
        with self.neo4j_driver.session() as neo_session:
            neo_session.run(f"CREATE (e:{entity_type} $props)", props=properties)

    def query_graph(self, cypher: str, **kwargs) -> list[dict[str, Any]]:
        """
        Execute an arbitrary read Cypher query against Neo4j.

        Args:
            cypher:   Cypher query string.  Use ``$param`` placeholders.
            **kwargs: Named parameters forwarded to the query.

        Returns:
            List of record dicts.
        """
        with self.neo4j_driver.session() as neo_session:
            result = neo_session.run(cypher, **kwargs)
            return [dict(record) for record in result]

    def get_relationships(
        self,
        node_type: str,
        node_id: str,
        rel_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve outgoing relationships for a node identified by ``id``.

        Args:
            node_type: Cypher label of the source node.
            node_id:   Value of the ``id`` property on the source node.
            rel_type:  Optional relationship type filter (e.g. ``"MODIFIED_BY"``).
                       If ``None``, all relationship types are returned.

        Returns:
            List of record dicts containing ``n`` (source), ``r`` (rel), ``m`` (target).
        """
        if rel_type:
            cypher = (
                f"MATCH (n:{node_type} {{id: $id}})-[r:{rel_type}]->(m) RETURN n, r, m"
            )
        else:
            cypher = f"MATCH (n:{node_type} {{id: $id}})-[r]->(m) RETURN n, r, m"

        with self.neo4j_driver.session() as neo_session:
            result = neo_session.run(cypher, id=node_id)
            return [dict(record) for record in result]
