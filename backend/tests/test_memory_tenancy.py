"""Column-backed ownership at the vector and graph storage boundaries."""

from unittest.mock import MagicMock, patch

import pytest
from database import ensure_memory_graph_schema
from memory_client import MemoryClient

from memory.engram_processor import DeepSeekEngramProcessor, EngramType


def test_memory_store_uses_explicit_company_in_both_stores():
    driver = MagicMock()
    client = MemoryClient(neo4j_driver=driver)
    with (
        patch("llm_proxy_client.LLMProxyClient") as proxy,
        patch("memory_client.Session") as session,
    ):
        proxy.return_value.embed.return_value = [0.5]
        client.store("decision", {"company_id": 999}, company_id=7)
    call = session.return_value.__enter__.return_value.execute.call_args
    assert "company_id" in str(call.args[0])
    assert call.args[1]["company_id"] == 7
    graph_call = driver.session.return_value.__enter__.return_value.run.call_args
    assert "company_id: $company_id" in graph_call.args[0]
    assert graph_call.kwargs["company_id"] == 7


@pytest.mark.parametrize(
    "companies, legacy", [([7], True), ([7], False), ([], True), ([], False)]
)
def test_memory_search_filters_before_limit_and_marks_legacy(companies, legacy):
    client = MemoryClient(neo4j_driver=MagicMock())
    with (
        patch("llm_proxy_client.LLMProxyClient") as proxy,
        patch("memory_client.Session") as session,
    ):
        proxy.return_value.embed.return_value = [0.5]
        db = session.return_value.__enter__.return_value
        db.execute.return_value = [("old", {}, 0.9, None), ("owned", {}, 0.8, 7)]
        results = client.search_similar(
            "query", company_ids=companies, include_legacy=legacy
        )
    query, params = db.execute.call_args.args
    query = str(query)
    assert query.index("WHERE") < query.index("ORDER BY") < query.index("LIMIT")
    assert "company_id = ANY(:company_ids)" in query
    assert ("OR company_id IS NULL" in query) is legacy
    assert params["company_ids"] == companies
    assert [result["legacy"] for result in results] == [True, False]
    assert [result["company_id"] for result in results] == [None, 7]


def test_engram_company_propagates_without_trusting_metadata():
    processor = DeepSeekEngramProcessor()
    with (
        patch.object(processor, "_process_with_deepseek", return_value="summary"),
        patch.object(processor, "_create_engram_node", return_value="engram") as graph,
        patch.object(processor, "_store_in_vector_db") as vector,
    ):
        processor.burn_engram(
            "agent", "PO", "decision", metadata={"company_id": 999}, company_id=7
        )
    assert graph.call_args.kwargs["company_id"] == 7
    assert vector.call_args.args[2] == 7


def test_engram_node_has_shared_label_and_company_property():
    processor = DeepSeekEngramProcessor()
    processor._driver = MagicMock()
    processor._create_engram_node(
        EngramType.CODE_REVIEW, "agent", "QA", "summary", {}, 7
    )
    call = processor._driver.session.return_value.__enter__.return_value.run.call_args
    assert "CREATE (e:Episodic:Episodic_CodeReview" in call.args[0]
    assert "company_id: $company_id" in call.args[0]
    assert call.kwargs["company_id"] == 7


def test_engram_vector_insert_has_company_column():
    processor = DeepSeekEngramProcessor()
    with (
        patch("llm_proxy_client.LLMProxyClient") as proxy,
        patch("sqlmodel.Session") as session,
    ):
        proxy.return_value.embed.return_value = [0.5]
        processor._store_in_vector_db("summary", {"company_id": 999}, 7)
    query, params = session.return_value.__enter__.return_value.execute.call_args.args
    assert "metadata, company_id)" in str(query)
    assert params["company_id"] == 7


def test_graph_schema_backfills_without_rewriting_metadata():
    driver = MagicMock()
    with patch("database.Session") as session:
        session.return_value.__enter__.return_value.exec.return_value.all.return_value = [
            7,
            8,
        ]
        ensure_memory_graph_schema(driver)
    queries = [
        call.args[0]
        for call in driver.session.return_value.__enter__.return_value.run.call_args_list
    ]
    assert "SET e:Episodic" in queries[0]
    assert "e.company_id IS NULL" in queries[1]
    assert "fromJsonMap(e.metadata).company_id" in queries[1]
    assert "WHERE company_id IN $company_ids" in queries[1]
    calls = driver.session.return_value.__enter__.return_value.run.call_args_list
    assert calls[1].kwargs["company_ids"] == [7, 8]
    assert "SET e.metadata" not in queries[1]
    assert "ON (e.company_id)" in queries[2]
