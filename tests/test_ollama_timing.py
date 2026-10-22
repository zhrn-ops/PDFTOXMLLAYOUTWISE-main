import io
import json

from pdf_to_jats.llm.ollama_client import OllamaClient


def test_ollama_reports_server_breakdown_without_changing_result(monkeypatch):
    raw = {
        "message": {"content": '{"authors": []}'},
        "load_duration": 2_000_000_000,
        "prompt_eval_duration": 3_000_000_000,
        "eval_duration": 5_000_000_000,
        "total_duration": 10_000_000_000,
    }
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(json.dumps(raw).encode()),
    )
    messages = []
    result = OllamaClient().classify("parse authors", {}, progress=messages.append)
    assert result == {"authors": []}
    assert "Qwen Model loading: 2.00 seconds." in messages
    assert "Qwen Prompt processing: 3.00 seconds." in messages
    assert "Qwen Response generation: 5.00 seconds." in messages
    assert "Qwen Total server processing: 10.00 seconds." in messages


def test_ollama_does_not_invent_missing_server_timings(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *args, **kwargs: io.BytesIO(b'{"message":{"content":"{}"}}'),
    )
    messages = []
    assert OllamaClient().classify("parse", {}, progress=messages.append) == {}
    assert not any("Model loading:" in message for message in messages)
