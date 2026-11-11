import json
from types import SimpleNamespace
import urllib.error

import pytest

from pdf_to_jats.llm.errors import LLMUnavailable, LLMResponseError
from pdf_to_jats.llm.ollama_client import OllamaClient
from pdf_to_jats.llm.openrouter_client import OpenRouterClient
from pdf_to_jats.llm.primary_client import PrimaryLLMClient


def failing(error):
    def classify(*args, **kwargs):
        raise error
    return SimpleNamespace(model="test", classify=classify)


def test_programming_error_does_not_trigger_provider_fallback():
    client = PrimaryLLMClient(failing(TypeError("bug")), failing(AssertionError("fallback called")))
    with pytest.raises(TypeError, match="bug"):
        client.classify("prompt", {})


def test_expected_failure_falls_back_without_logging_document_text(caplog):
    messages = []
    client = PrimaryLLMClient(failing(LLMUnavailable("PRIVATE_DOCUMENT_SENTINEL")),
                              SimpleNamespace(classify=lambda *a: {"authors": []}))
    assert client.classify("prompt", {}, messages.append) == {"authors": []}
    assert "PRIVATE_DOCUMENT_SENTINEL" not in caplog.text + str(messages)


@pytest.mark.parametrize("client", [OllamaClient(), OpenRouterClient(api_key="test")])
def test_transport_failures_are_typed(monkeypatch, client):
    monkeypatch.setattr("urllib.request.urlopen", failing(urllib.error.URLError("private")).classify)
    with pytest.raises(LLMUnavailable, match="Provider connection failed"):
        client.classify("prompt", {})


@pytest.mark.parametrize("client", [OllamaClient(), OpenRouterClient(api_key="test")])
def test_serialization_bugs_are_not_provider_failures(client):
    with pytest.raises(TypeError):
        client.classify("prompt", {"bad": object()})


@pytest.mark.parametrize("client", [OllamaClient(), OpenRouterClient(api_key="test")])
def test_invalid_provider_json_is_typed(monkeypatch, client):
    from io import BytesIO
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(b"not json"))
    with pytest.raises(LLMResponseError):
        client.classify("prompt", {})


def test_legacy_file_key_is_ignored_and_warning_is_redacted(tmp_path, monkeypatch, caplog):
    from pdf_to_jats.utils.config import load_config
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / "output").mkdir()
    (tmp_path / "output/openrouter_settings.json").write_text(json.dumps(
        {"api_key": "PRIVATE_KEY_SENTINEL", "model": "chosen"}))
    config = load_config()
    assert config.openrouter_api_key == ""
    assert config.openrouter_model == "chosen"
    assert "OPENROUTER_API_KEY" in caplog.text
    assert "PRIVATE_KEY_SENTINEL" not in caplog.text
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")
    assert load_config().openrouter_api_key == "environment-key"


@pytest.mark.parametrize("data", ["[]", "null", "42", "broken"])
def test_malformed_settings_do_not_crash(tmp_path, monkeypatch, data):
    from pdf_to_jats.utils.config import load_config
    monkeypatch.chdir(tmp_path)
    (tmp_path / "output").mkdir()
    (tmp_path / "output/openrouter_settings.json").write_text(data)
    assert load_config().openrouter_model


@pytest.mark.parametrize("body", [[], {"output": [42]}, {"output_text": 42},
                                  {"output": [{"content": [42]}]},
                                  {"output_text": "[]"}])
def test_openrouter_malformed_response_is_expected_failure(monkeypatch, body):
    from io import BytesIO
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(json.dumps(body).encode()))
    with pytest.raises(LLMResponseError):
        OpenRouterClient(api_key="test").classify("prompt", {})


@pytest.mark.parametrize("body", [[], {"message": 42}, {"message": {"content": 42}},
                                  {"message": {"content": [42]}},
                                  {"message": {"content": "[]"}}])
def test_ollama_malformed_response_is_expected_failure(monkeypatch, body):
    from io import BytesIO
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **kw: BytesIO(json.dumps(body).encode()))
    with pytest.raises(LLMResponseError):
        OllamaClient().classify("prompt", {})


def test_http_error_does_not_expose_provider_body(monkeypatch):
    from io import BytesIO
    error = urllib.error.HTTPError("https://example.invalid", 400, "Bad request", {},
                                  BytesIO(b"PRIVATE_DOCUMENT_SENTINEL"))
    monkeypatch.setattr("urllib.request.urlopen", failing(error).classify)
    with pytest.raises(LLMUnavailable) as raised:
        OpenRouterClient(api_key="test").classify("prompt", {})
    assert "PRIVATE_DOCUMENT_SENTINEL" not in str(raised.value)


def test_internal_finish_error_stops_before_draft_generation(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from pdf_to_jats.gui.main_window import MainWindow
    from pdf_to_jats.utils.config import AppConfig
    monkeypatch.setattr("pdf_to_jats.gui.main_window.load_config", lambda: AppConfig(
        output_dir=tmp_path, generated_xml_dir=tmp_path,
        openrouter_settings_path=tmp_path / "settings.json"))
    window = MainWindow(headless=True)
    messages = []
    try:
        assert not any(button.text() == "Classify" for button in window.findChildren(QPushButton))
        monkeypatch.setattr(window, "_set_article_finish_busy", lambda busy: None)
        monkeypatch.setattr(window, "_log", messages.append)
        monkeypatch.setattr(window, "_update_document_model", failing(AssertionError("draft generation started")).classify)
        window._on_article_finish_complete({}, None, None, TypeError("PRIVATE_DOCUMENT_SENTINEL"))
        assert any("Internal" in message for message in messages)
        assert "PRIVATE_DOCUMENT_SENTINEL" not in str(messages)
    finally:
        window.close()
