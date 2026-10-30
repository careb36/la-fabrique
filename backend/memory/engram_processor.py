"""
DeepSeek Engram Processor - Episodic Memory Management

This module handles the "burning" of Engrams into the Neo4j Temporal Knowledge Graph.
Engrams are immutable episodic memory nodes that capture architectural decisions,
PRs, test results, and other critical state changes in the LangGraph workflow.

The DeepSeek LLM processes and summarizes decisions before writing to Neo4j.
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel
import neo4j

from llm.model_factory import get_llm_for_role, AgentRole
from app.memory_client import MemoryClient

logger = logging.getLogger(__name__)

# agent_id prefix of the engram each completed sprint's retrospective burns.
RETROSPECTIVE_AGENT_PREFIX = "retrospective_"


class EngramType(str, Enum):
    """Types of Engrams in the system."""
    CODE_REVIEW = "Episodic_CodeReview"
    SPRINT_DECISION = "Episodic_SprintDecision"
    ARCHITECTURAL_CHANGE = "Episodic_ArchitecturalChange"
    TEST_RESULT = "Episodic_TestResult"
    DEPLOYMENT = "Episodic_Deployment"
    TICKET_TRANSITION = "Episodic_TicketTransition"


class EngramProcessorError(Exception):
    """Custom exception for Engram processing errors."""
    pass


@dataclass
class EngramData:
    """Structured data for an Engram."""
    engram_type: EngramType
    agent_id: str
    agent_role: str
    decision_summary: str
    related_semantic_refs: List[str]  # e.g., ["Semantic_JavaClass:com.foo.Bar", "Semantic_OracleTable:ORDER"]
    raw_context: Dict[str, Any]
    metadata: Dict[str, Any]


class DeepSeekEngramProcessor:
    """
    Processor that uses DeepSeek to parse decisions and burn Engrams into Neo4j TKG.
    
    The processor:
    1. Uses DeepSeek to summarize/extract key information from decisions
    2. Creates Episodic nodes in Neo4j
    3. Creates temporal edges (e.g., MODIFIED_BY, RELATED_TO) linking to Semantic nodes
    """
    
    def __init__(self, neo4j_uri: Optional[str] = None, neo4j_user: Optional[str] = None, neo4j_password: Optional[str] = None):
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.neo4j_user = neo4j_user or os.getenv("NEO4J_USER", "neo4j")
        self.neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD")
        
        self._driver: Optional[neo4j.Driver] = None
    
    @property
    def driver(self) -> neo4j.Driver:
        """Lazy initialization of Neo4j driver."""
        if self._driver is None:
            try:
                self._driver = neo4j.GraphDatabase.driver(
                    self.neo4j_uri,
                    auth=(self.neo4j_user, self.neo4j_password)
                )
                logger.info(f"Connected to Neo4j at {self.neo4j_uri}")
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
                raise EngramProcessorError(f"Neo4j connection failed: {e}")
        return self._driver
    
    def burn_engram(
        self,
        agent_id: str,
        role: str,
        decision_summary: str,
        related_semantic_refs: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        company_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Burn an Engram into the Temporal Knowledge Graph and Vector Store.
        
        This method:
        1. Uses DeepSeek to process the decision
        2. Creates an Episodic node in Neo4j
        3. Stores the summary in pgvector for semantic RAG
        4. Links it to relevant Semantic nodes in Neo4j
        """
        if related_semantic_refs is None:
            related_semantic_refs = []
        if metadata is None:
            metadata = {}
        
        # Determine Engram type based on role and context
        engram_type = self._determine_engram_type(role, metadata)
        
        # Use DeepSeek to process and summarize the decision
        processed_summary = self._process_with_deepseek(decision_summary, engram_type)
        
        # 1. Create the Engram in Neo4j
        engram_id = self._create_engram_node(
            engram_type=engram_type,
            agent_id=agent_id,
            agent_role=role,
            summary=processed_summary,
            metadata=metadata,
            company_id=company_id,
        )
        
        # 2. Store in pgvector for semantic RAG
        try:
            vector_metadata = {
                **metadata,
                "engram_id": engram_id,
                "engram_type": engram_type.value,
                "agent_role": role,
                "is_engram": True
            }
            self._store_in_vector_db(processed_summary, vector_metadata, company_id)
        except Exception as e:
            logger.warning(f"Failed to store engram vector: {e}")

        # 3. Create temporal edges to related Semantic nodes
        if related_semantic_refs:
            self._create_temporal_edges(engram_id, related_semantic_refs)
        
        logger.info(f"Burned Engram {engram_id} for agent {agent_id} ({role})")
        
        return {
            "engram_id": engram_id,
            "engram_type": engram_type.value,
            "status": "burned",
            "summary": processed_summary[:200]
        }

    def _store_in_vector_db(self, content: str, metadata: Dict[str, Any], company_id: Optional[int] = None):
        """Helper to store in pgvector only."""
        from llm_proxy_client import LLMProxyClient
        from sqlmodel import Session, text
        from database import engine
        
        client = LLMProxyClient()
        embedding = client.embed(content)
        if embedding:
            with Session(engine) as session:
                session.execute(
                    text("INSERT INTO vector_memory (content, embedding, metadata, company_id) VALUES (:c, :e, :m, :company_id)"),
                    {"c": content, "e": json.dumps(embedding), "m": json.dumps(metadata), "company_id": company_id}
                )
                session.commit()
    
    def _determine_engram_type(self, role: str, metadata: Dict[str, Any]) -> EngramType:
        """
        Choose the most specific ``EngramType`` for the incoming event.

        Priority order:
        1. ``action_type`` metadata field (explicit classification from the caller).
        2. Agent role (Architect/PO → architectural change).
        3. Default to ``SPRINT_DECISION``.

        The ``action_type`` field is set by ``burn_engram_node`` in ``graph.py``:
        ``"test_result"`` when tests passed, ``"code_review"`` otherwise.
        """
        if metadata.get("action_type") == "code_review":
            return EngramType.CODE_REVIEW
        elif metadata.get("action_type") == "test_result":
            return EngramType.TEST_RESULT
        elif metadata.get("action_type") == "deployment":
            return EngramType.DEPLOYMENT
        elif metadata.get("action_type") == "ticket_transition":
            return EngramType.TICKET_TRANSITION
        elif role in ["Architect", "PO"]:
            return EngramType.ARCHITECTURAL_CHANGE
        else:
            return EngramType.SPRINT_DECISION
    
    def _process_with_deepseek(self, decision_summary: str, engram_type: EngramType) -> str:
        """
        Use DeepSeek to process and summarize the decision.
        
        This extracts key architectural decisions, patterns, and relationships.
        """
        model = get_llm_for_role("EngramProcessor")
        
        prompt = f"""Analyze this {engram_type.value} decision and extract:
1. Key architectural patterns or decisions
2. Related code entities or database tables
3. Impact assessment (brief)

Decision: {decision_summary}

Output as JSON with keys: patterns, entities, impact. Keep it concise."""

        try:
            from langchain_core.messages import HumanMessage
            response = model.invoke([HumanMessage(content=prompt)])
            # Extract summary from response
            return f"{decision_summary}\n\n[AI Analysis]: {response.content[:500]}"
        except Exception as e:
            logger.warning(f"DeepSeek processing failed, using raw summary: {e}")
            return decision_summary
    
    def _create_engram_node(
        self,
        engram_type: EngramType,
        agent_id: str,
        agent_role: str,
        summary: str,
        metadata: Dict[str, Any],
        company_id: Optional[int] = None,
    ) -> str:
        """Create an Episodic node in Neo4j."""
        engram_id = f"engram_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{agent_id}"
        
        cypher = f"""
        CREATE (e:Episodic:{engram_type.value} {{
            id: $engram_id,
            agent_id: $agent_id,
            company_id: $company_id,
            agent_role: $agent_role,
            summary: $summary,
            metadata: $metadata,
            created_at: datetime($timestamp),
            version: 1
        }})
        RETURN e.id
        """
        
        try:
            with self.driver.session() as session:
                result = session.run(
                    cypher,
                    engram_id=engram_id,
                    agent_id=agent_id,
                    company_id=company_id,
                    agent_role=agent_role,
                    summary=summary,
                    metadata=json.dumps(metadata),
                    timestamp=datetime.now().isoformat()
                )
                record = result.single()
                return record[0] if record else engram_id
        except Exception as e:
            logger.error(f"Failed to create Engram node: {e}")
            raise EngramProcessorError(f"Engram creation failed: {e}")
    
    def _create_temporal_edges(self, engram_id: str, semantic_refs: List[str]):
        """
        Create temporal edges between Engram and Semantic nodes.
        
        Links like MODIFIED_BY, RELATED_TO connect Engrams to:
        - Semantic_JavaClass
        - Semantic_OracleTable
        - Semantic_WorkPackage
        """
        with self.driver.session() as session:
            for ref in semantic_refs:
                parts = ref.split(":")
                if len(parts) != 2:
                    continue
                    
                node_type, node_id = parts
                
                # Map to proper Neo4j labels
                label_map = {
                    "Semantic_JavaClass": "JavaClass",
                    "Semantic_OracleTable": "OracleTable",
                    "Semantic_WorkPackage": "WorkPackage"
                }
                neo4j_label = label_map.get(node_type, node_type)
                
                cypher = f"""
                MATCH (e:Episodic {{id: $engram_id}})
                MERGE (s:{neo4j_label} {{id: $node_id}})
                MERGE (e)-[:MODIFIED_BY]->(s)
                RETURN e.id, s.id
                """
                
                try:
                    session.run(cypher, engram_id=engram_id, node_id=node_id)
                except Exception as e:
                    logger.warning(f"Failed to create edge to {ref}: {e}")
    
    def query_engrams(
        self,
        agent_id: Optional[str] = None,
        engram_type: Optional[EngramType] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Return raw Episodic node dicts from Neo4j, ordered by recency.

        Args:
            agent_id:    Filter to a specific agent (optional).
            engram_type: Filter to a specific engram type label (optional).
            limit:       Maximum number of results.

        Returns:
            List of property dicts for each matching Episodic node.
        """
        cypher = "MATCH (e:Episodic) "

        conditions = []
        params: Dict[str, Any] = {"limit": limit}

        if agent_id:
            conditions.append("e.agent_id = $agent_id")
            params["agent_id"] = agent_id
        if engram_type:
            conditions.append(f"e:{engram_type.value}")

        if conditions:
            cypher += "WHERE " + " AND ".join(conditions)

        cypher += " RETURN e ORDER BY e.created_at DESC LIMIT $limit"

        try:
            with self.driver.session() as session:
                result = session.run(cypher, params)
                return [dict(record["e"]) for record in result]
        except Exception as e:
            logger.error(f"Failed to query Engrams: {e}")
            return []

    def query_relevant_engrams(
        self,
        story: str,
        limit: int = 5,
        role_filter: Optional[str] = None,
        company_id: Optional[int] = None,
    ) -> str:
        """
        Improved RAG: Combined Semantic (pgvector) + Structural (Neo4j) search.
        
        Decisions are ranked by semantic similarity to the story and 
        complemented by the architectural context from the graph.
        """
        # 1. Semantic Search via pgvector
        semantic_results = []
        try:
            mem_client = MemoryClient(neo4j_driver=self.driver)
            semantic_results = mem_client.search_similar(
                story, limit=limit, company_ids=[company_id] if company_id is not None else []
            )
        except Exception as e:
            logger.warning(f"Semantic engram search failed: {e}")

        # 2. Structural/Keyword Search via Neo4j
        graph_context = self._query_graph_rag(story, limit=limit, role_filter=role_filter, company_id=company_id)
        
        # 3. Combine and Format
        if not semantic_results and not graph_context:
            return ""

        lines = ["--- Past Architectural Decisions (RAG Context) ---"]
        
        if semantic_results:
            lines.append("## Semantic Matches (from pgvector):")
            for res in semantic_results:
                sim = res.get("similarity", 0)
                content = res.get("content", "")[:400]
                lines.append(f"- [Score: {sim:.2f}] {content}")
        
        if graph_context:
            # Strip original headers from internal graph RAG output
            clean_graph = graph_context.replace("--- Past Architectural Decisions (RAG Context) ---", "").replace("--- End of RAG Context ---", "").strip()
            if clean_graph:
                lines.append("\n## Graph Relationships (from Neo4j):")
                lines.append(clean_graph)

        lines.append("--- End of RAG Context ---")
        return "\n".join(lines)

    def _query_graph_rag(
        self,
        story: str,
        limit: int = 5,
        role_filter: Optional[str] = None,
        company_id: Optional[int] = None,
    ) -> str:
        """
        Keyword-based search over the Temporal Knowledge Graph.
        """
        normalized = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in story.lower())
        stop_words = {
            "this", "that", "with", "from", "into", "para", "como", "sobre", "pero",
            "the", "and", "for", "una", "unos", "unas", "de", "del", "por", "con", "sin",
        }
        keywords = [w for w in normalized.split() if len(w) > 3 and w not in stop_words][:10]

        params: Dict[str, Any] = {"limit": limit, "company_id": company_id}
        role_condition = "AND e.company_id = $company_id "
        if role_filter:
            # Sprint retrospectives are lessons for every role, not only the
            # ScrumMaster who records them.
            role_condition += (
                "AND (e.agent_role = $role_filter "
                "OR e.agent_id STARTS WITH $retrospective_prefix) "
            )
            params["role_filter"] = role_filter
            params["retrospective_prefix"] = RETROSPECTIVE_AGENT_PREFIX

        if keywords:
            params["keywords"] = keywords
            cypher = f"""
            MATCH (e:Episodic)
            WHERE any(kw IN $keywords WHERE toLower(e.summary) CONTAINS kw)
            {role_condition}
            WITH e,
                 size([kw IN $keywords WHERE toLower(e.summary) CONTAINS kw]) AS match_score
            OPTIONAL MATCH (e)-[:MODIFIED_BY|RELATED_TO]->(s)
            RETURN
                e.id         AS id,
                e.agent_role AS role,
                e.summary    AS summary,
                e.created_at AS ts,
                labels(e)    AS engram_types,
                collect(s.id)[..3] AS related_nodes,
                match_score
            ORDER BY match_score DESC, e.created_at DESC
            LIMIT $limit
            """
        else:
            # No usable keywords – fall back to most-recent engrams.
            cypher = f"""
            MATCH (e:Episodic)
            WHERE 1=1 {role_condition}
            OPTIONAL MATCH (e)-[:MODIFIED_BY|RELATED_TO]->(s)
            RETURN
                e.id         AS id,
                e.agent_role AS role,
                e.summary    AS summary,
                e.created_at AS ts,
                labels(e)    AS engram_types,
                collect(s.id)[..3] AS related_nodes,
                0            AS match_score
            ORDER BY e.created_at DESC
            LIMIT $limit
            """

        try:
            with self.driver.session() as session:
                result = session.run(cypher, params)
                records = [dict(r) for r in result]
        except Exception as e:
            logger.warning("Graph RAG query failed: %s", e)
            return ""

        if not records:
            return ""

        lines = ["--- Past Architectural Decisions (RAG Context) ---"]
        for r in records:
            ts = r.get("ts", "unknown time")
            role = r.get("role", "Agent")
            summary = (r.get("summary") or "")[:400]
            engram_types: list = r.get("engram_types") or []
            related: list = r.get("related_nodes") or []
            match_score = r.get("match_score", 0)

            # Pick the most specific Episodic_* label for display.
            etype = next((t for t in engram_types if t.startswith("Episodic_")), "")

            header = f"[{ts}] [{role}]"
            if etype:
                header += f" [{etype}]"
            if match_score:
                header += f" (relevance: {match_score} keyword match(es))"
            if related:
                header += f"\n  ↳ affects: {', '.join(str(n) for n in related[:3])}"
            lines.append(f"{header}\n  {summary}")
        lines.append("--- End of RAG Context ---")
        return "\n".join(lines)
    
    def close(self):
        """Close Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None


# Singleton instance
_engram_processor: Optional[DeepSeekEngramProcessor] = None


def get_engram_processor() -> DeepSeekEngramProcessor:
    """Get or create the Engram processor singleton."""
    global _engram_processor
    if _engram_processor is None:
        _engram_processor = DeepSeekEngramProcessor()
    return _engram_processor
