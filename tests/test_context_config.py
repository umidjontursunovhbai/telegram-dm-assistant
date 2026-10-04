import pytest

from telegram_dm_assistant.config import Config


def test_context_is_explicit_opt_in(monkeypatch):
    for key, value in {"TG_API_ID": "123", "TG_API_HASH": "dummy",
                       "LLM_API_KEY": "dummy", "LLM_MODEL": "dummy",
                       "DM_SEND_ENABLED": "false"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DM_CONTEXT_ENABLED", raising=False)
    assert hasattr(Config.from_env(), "context_enabled")
    assert not Config.from_env().context_enabled
    monkeypatch.setenv("DM_CONTEXT_ENABLED", "true")
    assert Config.from_env().context_enabled
    monkeypatch.setenv("DM_CONTEXT_ENABLED", "typo")
    with pytest.raises(ValueError, match="DM_CONTEXT_ENABLED"):
        Config.from_env()
