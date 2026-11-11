import logging
import pytest

from pdf_to_jats.utils.config import AppConfig, save_openrouter_settings
from pdf_to_jats.utils.logger import redact_secrets


def config_for(tmp_path, key="sk-or-v1-supersecret123456"):
    return AppConfig(
        output_dir=tmp_path,
        generated_xml_dir=tmp_path / "generated",
        openrouter_settings_path=tmp_path / "openrouter_settings.json",
        openrouter_api_key=key,
    )


def test_settings_do_not_persist_the_key_by_default(tmp_path):
    config = config_for(tmp_path)
    save_openrouter_settings(config)
    text = config.openrouter_settings_path.read_text(encoding="utf-8")
    assert "api_key" not in text
    assert "supersecret" not in text


def test_settings_reject_legacy_plaintext_key_opt_in(tmp_path):
    config = config_for(tmp_path)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        save_openrouter_settings(config, include_api_key=True)
    assert not config.openrouter_settings_path.exists()


def test_redact_secrets_masks_keys_and_bearer_values():
    assert "sk-or-v1-abcdefgh12345678" not in redact_secrets(
        "request failed: sk-or-v1-abcdefgh12345678"
    )
    assert "abc12345678" not in redact_secrets("api_key=abc12345678")
    assert "abc12345678" not in redact_secrets("Authorization: Bearer abc12345678")


def test_logging_filter_redacts_formatted_arguments():
    from pdf_to_jats.utils.logger import _RedactionFilter

    record = logging.LogRecord(
        "test", logging.WARNING, __file__, 1,
        "provider failed with %s", ("sk-or-v1-abcdefgh12345678",), None,
    )
    _RedactionFilter().filter(record)
    assert "abcdefgh" not in record.getMessage()
    assert record.levelno == logging.WARNING
