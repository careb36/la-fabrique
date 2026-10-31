"""
Model routing in ``POST /v1/chat/completions`` (#102).

A model id picks its provider by prefix and must be in that provider's
catalogue; nothing unknown is silently sent to Gemini.  Provider errors come
back with provider, status and message, and a 429/5xx falls back only to a
model that is in a catalogue.  Provider HTTP is faked by replacing
``requests.post``.
"""

import pytest
from conftest import FakeResponse, gemini_ok, openai_ok


def _chat(client, model, content="Write a function"):
    payload = {"messages": [{"role": "user", "content": content}]}
    if model is not None:
        payload["model"] = model
    return client.post("/v1/chat/completions", json=payload)


@pytest.mark.parametrize(
    ("model", "provider"),
    [
        ("deepseek-v4-pro", "deepseek"),
        ("qwen3.7-plus", "qwen"),
        ("gemini-3.8-flash", "gemini"),
    ],
)
def test_model_routes_to_the_provider_its_prefix_names(client, upstream, model, provider):
    upstream.set("deepseek", openai_ok("from deepseek"))
    upstream.set("qwen", openai_ok("from qwen"))
    upstream.set("gemini", gemini_ok("from gemini"))

    resp = _chat(client, model)

    assert resp.status_code == 200
    assert upstream.providers_called() == [provider]
    body = resp.get_json()
    assert body.get("served_model") == model
    assert body.get("provider") == provider
    assert body["choices"][0]["message"]["content"] == f"from {provider}"


def test_deprecated_gemini_id_is_aliased_and_reported(client, upstream):
    upstream.set("gemini", gemini_ok())

    resp = _chat(client, "gemini-2.5-flash")

    assert resp.status_code == 200
    assert "models/gemini-3.8-flash:generateContent" in upstream.calls[0]["url"]
    assert resp.get_json().get("served_model") == "gemini-3.8-flash"


@pytest.mark.parametrize("model", ["kimi-k2.6", "deepseek-coder", "gemini-9-ultra"])
def test_unknown_model_is_a_400_listing_what_is_available(client, upstream, model):
    resp = _chat(client, model)

    assert resp.status_code == 400
    body = resp.get_json()
    assert body.get("error") == "unknown_model"
    assert body.get("model") == model
    assert body.get("available") == [
        "deepseek-flash",
        "deepseek-v4-pro",
        "gemini-3.1-pro-preview",
        "gemini-3.8-flash",
        "qwen3.6-flash",
        "qwen3.7-plus",
    ]
    assert upstream.calls == []


@pytest.mark.parametrize("model", [None, "", "   "])
def test_empty_model_is_a_400(client, upstream, model):
    resp = _chat(client, model)

    assert resp.status_code == 400
    assert resp.get_json().get("available")
    assert upstream.calls == []


def test_upstream_500_is_returned_with_provider_status_and_message(client, upstream, proxy, monkeypatch):
    # Only DeepSeek is configured, so there is nothing to fall back to.
    monkeypatch.setattr(proxy, "_available_qwen_models", set())
    monkeypatch.setattr(proxy, "_available_models", set())
    upstream.set("deepseek", FakeResponse(500, {"message": "internal failure"}))

    resp = _chat(client, "deepseek-v4-pro")

    assert resp.status_code == 502
    body = resp.get_json()
    assert body.get("provider") == "deepseek"
    assert body.get("status") == 500
    assert body.get("message") == "internal failure"
    assert "choices" not in body


def test_upstream_4xx_is_an_error_without_fallback(client, upstream):
    upstream.set("deepseek", FakeResponse(401, {"error": {"message": "invalid api key"}}))
    upstream.set("qwen", openai_ok())

    resp = _chat(client, "deepseek-v4-pro")

    assert resp.status_code == 502
    assert resp.get_json()["status"] == 401
    assert resp.get_json()["message"] == "invalid api key"
    assert upstream.providers_called() == ["deepseek"]


def test_ok_status_without_choices_is_an_error_not_an_empty_answer(client, upstream):
    upstream.set("qwen", FakeResponse(200, {"id": "x", "choices": []}))

    resp = _chat(client, "qwen3.7-plus")

    assert resp.status_code == 502
    assert resp.get_json()["provider"] == "qwen"


def test_quota_error_falls_back_to_a_catalogue_model(client, upstream):
    upstream.set("deepseek", FakeResponse(429, {"error": {"message": "quota exhausted"}}))
    upstream.set("qwen", openai_ok("answer from qwen"))

    resp = _chat(client, "deepseek-v4-pro")

    assert resp.status_code == 200
    body = resp.get_json()
    assert upstream.providers_called() == ["deepseek", "qwen"]
    assert upstream.calls[1]["json"]["model"] == "qwen3.6-flash"
    assert body.get("served_model") == "qwen3.6-flash"
    assert body.get("fallback_from", {}).get("status") == 429
    assert body["choices"][0]["message"]["content"] == "answer from qwen"


def test_5xx_fallback_skips_candidates_missing_from_the_catalogue(client, upstream, proxy, monkeypatch):
    # DeepSeek is configured but its catalogue lacks the fallback candidate.
    monkeypatch.setattr(proxy, "_available_deepseek_models", {"deepseek-v4-pro"})
    upstream.set("gemini", FakeResponse(503, {"error": {"message": "overloaded"}}))
    upstream.set("deepseek", openai_ok())
    upstream.set("qwen", openai_ok("answer from qwen"))

    resp = _chat(client, "gemini-3.8-flash")

    assert resp.status_code == 200
    assert upstream.providers_called() == ["gemini", "qwen"]
    assert resp.get_json().get("served_model") == "qwen3.6-flash"


def test_failed_fallbacks_return_the_original_error(client, upstream):
    upstream.set("qwen", FakeResponse(500, {"message": "qwen down"}))
    upstream.set("deepseek", FakeResponse(503, {"message": "deepseek down"}))
    upstream.set("gemini", FakeResponse(500, {"message": "gemini down"}))

    resp = _chat(client, "qwen3.7-plus")

    assert resp.status_code == 502
    body = resp.get_json()
    assert (body["provider"], body["status"], body["message"]) == ("qwen", 500, "qwen down")
    assert [a["provider"] for a in body["attempts"]] == ["qwen", "deepseek", "gemini"]


def test_upstream_timeout_defaults_to_110_seconds(client, upstream, proxy):
    upstream.set("deepseek", openai_ok())

    _chat(client, "deepseek-v4-pro")

    assert upstream.calls[0]["timeout"] == 110
    assert proxy.LLM_UPSTREAM_TIMEOUT_SECONDS == 110


def test_nemotron_routes_to_nebius_token_factory(nebius, client, upstream):
    upstream.set("nebius", openai_ok("from nemotron"))

    resp = _chat(client, "nvidia/Llama-3.1-Nemotron-70B-Instruct")

    assert resp.status_code == 200
    assert upstream.providers_called() == ["nebius"]
    assert upstream.calls[0]["url"] == (
        "https://api.tokenfactory.nebius.com/v1/chat/completions"
    )
    body = resp.get_json()
    assert body.get("provider") == "nebius"
    assert body.get("served_model") == "nvidia/Llama-3.1-Nemotron-70B-Instruct"
    assert body["choices"][0]["message"]["content"] == "from nemotron"


def test_nebius_reports_a_provider_error_with_its_status(nebius, client, upstream):
    # 400 is not retriable, so no cross-provider fallback masks the answer.
    upstream.set("nebius", FakeResponse(400, {"error": {"message": "model is not available"}}))

    resp = _chat(client, "nvidia/Llama-3.1-Nemotron-70B-Instruct")

    assert resp.status_code >= 400
    body = resp.get_json()
    assert body.get("provider") == "nebius"
    assert "model is not available" in (body.get("detail") or body.get("message") or str(body))
    assert upstream.providers_called() == ["nebius"]


def test_nebius_models_are_listed_with_a_tier(nebius, client):
    resp = client.get("/v1/models")

    assert resp.status_code == 200
    listed = {m["id"]: m for m in resp.get_json()["models"] if m["provider"] == "nebius"}
    assert set(listed) == {
        "nvidia/Llama-3.1-Nemotron-70B-Instruct",
        "nvidia/Nemotron-Nano-9B",
    }
    assert listed["nvidia/Nemotron-Nano-9B"]["tier"] == "fast"


def test_nebius_models_need_the_key(proxy, client):
    # The shared fixture sets no NEBIUS_API_KEY, so nothing from Nebius is listed.
    resp = client.get("/v1/models")

    assert resp.status_code == 200
    assert not [m for m in resp.get_json()["models"] if m["provider"] == "nebius"]


# ── How a call's token count is known ────────────────────────────────────────


def test_a_reported_count_is_usage(client, upstream):
    upstream.set("deepseek", openai_ok())
    body = client.post("/v1/chat/completions", json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]}).get_json()
    assert body["usage"]["total_tokens"] == 12
    assert body["usage_status"] == "reported"
    assert "usage_estimate" not in body


def test_a_missing_count_is_estimated_apart_and_never_shown_as_usage(client, upstream, proxy, monkeypatch):
    charged = []
    monkeypatch.setattr(proxy, "track_usage_in_db", lambda bu_id, tokens: charged.append(tokens))
    upstream.set("deepseek", FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}))
    body = client.post("/v1/chat/completions", json={"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi"}]}).get_json()
    assert "usage" not in body
    assert body["usage_status"] == "estimated"
    # The quota is still charged, with the estimate, so a budget cannot leak.
    assert charged == [body["usage_estimate"]] and body["usage_estimate"] > 0


def test_gemini_reports_its_own_count_or_the_estimate_stays_apart(client, upstream):
    upstream.set(
        "gemini",
        FakeResponse(
            200,
            {"candidates": [{"content": {"parts": [{"text": "hello"}]}}], "usageMetadata": {"totalTokenCount": 33}},
        ),
    )
    reported = client.post("/v1/chat/completions", json={"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "hi"}]}).get_json()
    assert (reported["usage"]["total_tokens"], reported["usage_status"]) == (33, "reported")

    upstream.set("gemini", gemini_ok())
    estimated = client.post("/v1/chat/completions", json={"model": "gemini-3.8-flash", "messages": [{"role": "user", "content": "hi"}]}).get_json()
    assert "usage" not in estimated
    assert estimated["usage_status"] == "estimated"


def test_env_values_are_trimmed(monkeypatch):
    """A .env edited on Windows leaves a CRLF, and a key with \\r is not a key."""
    from conftest import proxy_module

    monkeypatch.setenv("NEBIUS_API_KEY", "nvapi-abc\r\n")

    assert proxy_module._env("NEBIUS_API_KEY") == "nvapi-abc"
    assert proxy_module._env("NO_EXISTE", "por-defecto") == "por-defecto"


# ── NVIDIA's own gateway (integrate.api.nvidia.com) ─────────────────────────


def test_nemotron_ultra_routes_to_nvidias_gateway(nvidia, client, upstream):
    upstream.set("nvidia", openai_ok("from ultra"))

    resp = _chat(client, "nvidia/nemotron-3-ultra-550b-a55b")

    assert resp.status_code == 200
    assert upstream.providers_called() == ["nvidia"]
    assert upstream.calls[0]["url"] == (
        "https://integrate.api.nvidia.com/v1/chat/completions"
    )
    body = resp.get_json()
    assert body["provider"] == "nvidia"
    assert body["served_model"] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_the_shared_prefix_prefers_the_gateway_whose_key_is_configured(
    both_gateways, client, upstream
):
    upstream.set("nvidia", openai_ok("from ultra"))

    resp = _chat(client, "nvidia/nemotron-3-ultra-550b-a55b")

    assert resp.status_code == 200
    assert upstream.providers_called() == ["nvidia"]
    # The same id still resolves on Nebius when that is the only key.
    assert both_gateways.resolve_model("nvidia/nemotron-3-ultra-550b-a55b")[0] == "nvidia"


def test_nemotron_still_resolves_on_nebius_without_the_nvidia_key(nebius, client, upstream):
    upstream.set("nebius", openai_ok("from nebius"))

    resp = _chat(client, "nvidia/Llama-3.1-Nemotron-70B-Instruct")

    assert resp.status_code == 200
    assert upstream.providers_called() == ["nebius"]


def test_thinking_parameters_reach_the_provider(nvidia, client, upstream):
    upstream.set("nvidia", openai_ok("listo"))

    client.post("/v1/chat/completions", json={
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "messages": [{"role": "user", "content": "hola"}],
        "temperature": 1,
        "top_p": 0.95,
        "max_tokens": 16384,
        "chat_template_kwargs": {"enable_thinking": True},
    })

    sent = upstream.calls[0]["json"]
    assert sent["temperature"] == 1
    assert sent["top_p"] == 0.95
    assert sent["max_tokens"] == 16384
    assert sent["chat_template_kwargs"] == {"enable_thinking": True}


def test_a_nested_extra_body_is_flattened_before_the_call(nvidia, client, upstream):
    upstream.set("nvidia", openai_ok("listo"))

    client.post("/v1/chat/completions", json={
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "messages": [{"role": "user", "content": "hola"}],
        "extra_body": {"chat_template_kwargs": {"enable_thinking": True}},
    })

    sent = upstream.calls[0]["json"]
    assert "extra_body" not in sent
    assert sent["chat_template_kwargs"] == {"enable_thinking": True}


def test_reasoning_travels_in_the_answer(nvidia, client, upstream):
    upstream.set("nvidia", FakeResponse(200, {
        "choices": [{"message": {
            "role": "assistant",
            "content": "Cuatro.",
            "reasoning_content": "Dos más dos son cuatro.",
        }}],
    }))

    body = _chat(client, "nvidia/nemotron-3-ultra-550b-a55b").get_json()

    message = body["choices"][0]["message"]
    assert message["content"] == "Cuatro."
    assert message["reasoning_content"] == "Dos más dos son cuatro."


def test_streaming_is_refused_with_an_explanation(nvidia, client, upstream):
    resp = client.post("/v1/chat/completions", json={
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "messages": [{"role": "user", "content": "hola"}],
        "stream": True,
    })

    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "stream_unsupported"
    assert "stream=false" in body["message"]
    assert upstream.calls == []


def test_nvidia_models_are_listed_with_a_tier(nvidia, client):
    listed = {m["id"]: m for m in client.get("/v1/models").get_json()["models"]
              if m["provider"] == "nvidia"}

    assert set(listed) == {
        "nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia/nemotron-3-nano-30b-a3b",
    }
    assert listed["nvidia/nemotron-3-ultra-550b-a55b"]["tier"] == "strategic"
    assert listed["nvidia/nemotron-3-nano-30b-a3b"]["tier"] == "fast"


def test_an_id_served_by_both_gateways_is_listed_once(both_gateways, client):
    providers = [m["provider"] for m in client.get("/v1/models").get_json()["models"]
                 if m["id"] == "nvidia/nemotron-3-ultra-550b-a55b"]

    assert providers == ["nvidia"]


def test_a_stream_nested_in_extra_body_is_refused_too(nvidia, client, upstream):
    response = client.post("/v1/chat/completions", json={
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
        "messages": [{"role": "user", "content": "hola"}],
        "extra_body": {"stream": True},
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "stream_unsupported"


def test_catalogues_are_refreshed_every_interval_not_once():
    import app as proxy

    calls, sleeps = [], []
    proxy._refresh_forever(lambda: calls.append(1), interval=7, sleep=sleeps.append, rounds=3)
    assert calls == [1, 1, 1]
    assert sleeps == [7, 7, 7]


def test_a_failed_refresh_does_not_end_the_loop():
    import app as proxy

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("provider down")

    proxy._refresh_forever(flaky, interval=0, sleep=lambda _s: None, rounds=3)
    assert len(calls) == 3
