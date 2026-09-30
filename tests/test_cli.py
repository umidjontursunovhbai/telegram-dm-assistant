import pytest


def test_check_mode_does_not_create_client_or_connect(monkeypatch, capsys):
    from telegram_dm_assistant import main

    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "dummy")
    monkeypatch.setenv("LLM_API_KEY", "private-key")
    monkeypatch.setenv("LLM_MODEL", "dummy")
    monkeypatch.setenv("DM_SEND_ENABLED", "false")
    monkeypatch.setenv("DM_ALLOWED_USER_IDS", "42")
    monkeypatch.setattr(main, "TelegramClient", lambda *a, **kw: pytest.fail("client constructed"))
    assert main.main(["--check"]) == 0
    assert "private-key" not in capsys.readouterr().out


def test_login_mode_authenticates_without_listener(monkeypatch):
    from telegram_dm_assistant import main

    calls = []

    async def fake_login(config):
        calls.append(config.api_id)

    monkeypatch.setenv("TG_API_ID", "123")
    monkeypatch.setenv("TG_API_HASH", "dummy")
    monkeypatch.setenv("LLM_API_KEY", "dummy")
    monkeypatch.setenv("LLM_MODEL", "dummy")
    monkeypatch.setattr(main, "login", fake_login, raising=False)
    assert main.main(["--login"]) == 0
    assert calls == [123]


def test_no_mode_never_connects(monkeypatch):
    from telegram_dm_assistant import main

    monkeypatch.setattr(main, "TelegramClient", lambda *a, **kw: pytest.fail("client constructed"))
    with pytest.raises(SystemExit):
        main.main([])


@pytest.mark.asyncio
async def test_runtime_registers_incoming_private_handler_without_sending(tmp_path, monkeypatch):
    from telegram_dm_assistant import main
    from telegram_dm_assistant.config import Config

    class Client:
        def __init__(self, *args, **kwargs):
            self.handler = None
            self.filter = None
            self.disconnected = False

        async def start(self):
            return self

        async def get_me(self):
            return type("Owner", (), {"id": 1})()

        def add_event_handler(self, handler, event_filter):
            self.handler, self.filter = handler, event_filter

        async def run_until_disconnected(self):
            # No real Telegram events, network, or send here.
            assert self.handler is not None

        async def disconnect(self):
            self.disconnected = True

    client = Client()
    monkeypatch.setattr(main, "TelegramClient", lambda *args, **kwargs: client)
    config = Config(123, "placeholder", frozenset(), True, "openrouter", "dummy", "model",
                    "https://example.com/v1", tmp_path / "data", True)
    await main.run(config)
    assert client.handler.__self__.allow_all
    assert client.disconnected
    assert client.filter.incoming is True
    assert client.filter.func is not None
