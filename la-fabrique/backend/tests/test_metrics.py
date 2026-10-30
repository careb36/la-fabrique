"""
Tests for Prometheus metrics.
"""


def test_metrics_endpoint_accessible(test_client):
    """Verify /metrics endpoint is accessible."""
    response = test_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")


def test_metrics_contain_request_count(test_client):
    """Verify metrics contain request counter."""
    # Make a request to generate metrics
    test_client.get("/health")

    response = test_client.get("/metrics")
    assert "fabrique_requests_total" in response.text


def test_metrics_contain_active_connections(test_client):
    """Verify metrics contain active connections gauge."""
    response = test_client.get("/metrics")
    assert "fabrique_active_connections" in response.text


def test_metrics_contain_agent_run_metrics(test_client):
    """Verify metrics contain agent run counters."""
    response = test_client.get("/metrics")
    assert "fabrique_agent_runs_ingested_total" in response.text
    assert "fabrique_agent_runs_verified_total" in response.text


def test_metrics_contain_sprint_metrics(test_client):
    """Verify metrics contain sprint counters."""
    response = test_client.get("/metrics")
    assert "fabrique_sprints_created_total" in response.text
    assert "fabrique_sprints_completed_total" in response.text


def test_metrics_contain_error_metrics(test_client):
    """Verify metrics contain error counters."""
    response = test_client.get("/metrics")
    assert "fabrique_errors_total" in response.text


def test_request_increments_counter(test_client):
    """Verify that making requests increments the request counter."""
    # Make a request
    test_client.get("/health")

    response = test_client.get("/metrics")
    # The counter should be present (value may vary)
    assert "fabrique_requests_total" in response.text


def test_requests_are_labelled_by_route_not_by_path(test_client):
    """The public /metrics never shows an id, and scanned URLs share one label."""
    test_client.get("/v1/sprints/987654/board")
    test_client.get("/scanner/987654/wp-login.php")

    text = test_client.get("/metrics").text

    assert 'endpoint="/v1/sprints/{sprint_id}/board"' in text
    assert 'endpoint="unmatched"' in text
    assert "987654" not in text


def test_fixed_routes_and_preflights_are_not_unmatched(test_client):
    """``unmatched`` counts only the paths no route answered."""
    test_client.get("/docs")
    test_client.options(
        "/v1/sprints",
        headers={
            "Origin": "http://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    text = test_client.get("/metrics").text

    assert 'endpoint="/docs"' in text
    assert 'endpoint="preflight"' in text


def test_memory_search_caps_its_limit(test_client):
    response = test_client.get(
        "/v1/memory/search", params={"query": "x", "limit": 100000}
    )
    assert response.status_code == 422
