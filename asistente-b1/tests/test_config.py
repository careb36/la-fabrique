"""Settings: env beats file beats default, and defaults are always usable."""

from __future__ import annotations

import json

import pytest

from b1.config import DEFAULT_FACTORY_URL, Settings, app_dir, config_file


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("B1_HOME", str(tmp_path))
    for name in (
        "MODEL_BASE_URL", "MODEL", "MODEL_API_KEY", "FACTORY_URL", "VOICE_KEY", "LANGUAGE",
    ):
        monkeypatch.delenv("B1_" + name, raising=False)
    return tmp_path


def test_defaults_need_only_a_key():
    settings = Settings()
    assert settings.factory_url == DEFAULT_FACTORY_URL
    assert settings.missing() == ["model_api_key"]


def test_local_model_needs_no_key():
    settings = Settings(model_base_url="http://127.0.0.1:5100/v1")
    assert settings.is_local_model() is True
    assert settings.missing() == []


def test_remote_model_needs_a_key():
    settings = Settings(model_base_url="https://api.example.com/v1")
    assert settings.is_local_model() is False
    assert settings.missing() == ["model_api_key"]


def test_save_then_load_roundtrip():
    settings = Settings(voice_key="secreta", language="en", factory_company_id=7)
    path = settings.save()
    assert path == config_file()
    loaded = Settings.load()
    assert loaded.voice_key == "secreta"
    assert loaded.language == "en"
    assert loaded.factory_company_id == 7


def test_environment_wins_over_the_file(monkeypatch):
    Settings(voice_key="del-archivo").save()
    monkeypatch.setenv("B1_VOICE_KEY", "del-entorno")
    monkeypatch.setenv("B1_LANGUAGE", "en")
    loaded = Settings.load()
    assert loaded.voice_key == "del-entorno"
    assert loaded.language == "en"


def test_broken_file_falls_back_to_defaults():
    config_file().write_text("{ esto no es json", encoding="utf-8")
    assert Settings.load().language == "es"


def test_unknown_keys_in_the_file_are_ignored():
    config_file().write_text(json.dumps({"language": "en", "inventado": 1}), encoding="utf-8")
    assert Settings.load().language == "en"


def test_home_override_is_honoured(tmp_path):
    assert app_dir() == tmp_path


def test_urls_are_normalised():
    settings = Settings(model_base_url="http://x/v1/", factory_url="http://y/")
    assert settings.model_url_clean() == "http://x/v1"
    assert settings.factory_url_clean() == "http://y"


def test_model_tuning_from_the_environment_keeps_its_types(monkeypatch):
    monkeypatch.setenv("B1_MODEL_THINKING", "true")
    monkeypatch.setenv("B1_MODEL_MAX_TOKENS", "8192")
    monkeypatch.setenv("B1_MODEL_TOP_P", "0.95")

    loaded = Settings.load()

    assert loaded.model_thinking is True
    assert loaded.model_max_tokens == 8192
    assert loaded.model_top_p == 0.95


def test_a_bad_numeric_override_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv("B1_MODEL_MAX_TOKENS", "muchos")

    loaded = Settings.load()

    assert loaded.model_max_tokens == 4096
