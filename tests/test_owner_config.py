import pytest

from telegram_dm_assistant.config import Config


@pytest.mark.parametrize("flag,context,expected", [
    (None, "false", False), ("false", "false", False),
    ("true", "true", True), ("true", "false", "DM_CONTEXT_ENABLED"),
    ("typo", "true", "DM_REPLY_AS_OWNER"),
])
def test_owner_voice_requires_explicit_valid_opt_in_and_context(monkeypatch, flag, context, expected):
    for key, value in {"TG_API_ID": "123", "TG_API_HASH": "dummy",
                       "LLM_API_KEY": "dummy", "LLM_MODEL": "dummy",
                       "DM_SEND_ENABLED": "false", "DM_CONTEXT_ENABLED": context}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DM_REPLY_AS_OWNER", raising=False)
    if flag is not None:
        monkeypatch.setenv("DM_REPLY_AS_OWNER", flag)
    if isinstance(expected, str):
        with pytest.raises(ValueError, match=expected):
            Config.from_env()
    else:
        assert Config.from_env().reply_as_owner is expected


def test_direct_config_cannot_enable_owner_voice_without_context(tmp_path):
    with pytest.raises(ValueError, match="DM_CONTEXT_ENABLED"):
        Config(123, "dummy", frozenset(), False, "openrouter", "dummy", "dummy",
               "https://example.com", tmp_path, reply_as_owner=True)
