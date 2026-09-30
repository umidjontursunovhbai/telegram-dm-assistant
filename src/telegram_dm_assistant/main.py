"""Explicit CLI entry point; --check never connects to Telegram or the LLM."""

import argparse
import asyncio

from dotenv import load_dotenv
from telethon import TelegramClient, events

from .assistant import DMAssistant, DraftStore
from .config import Config
from .llm import LLMClient


async def run(config: Config) -> None:
    """Listen only when explicitly invoked with --run; draft-only by default."""
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if config.data_dir.stat().st_mode & 0o077:
        raise PermissionError("Data directory must be private (chmod 700)")
    with DraftStore(config.data_dir / "drafts.sqlite3") as store:
        client = TelegramClient(str(config.data_dir / "owner"), config.api_id, config.api_hash)
        try:
            await client.start()
            owner = await client.get_me()
            if owner is None:
                raise RuntimeError("Telegram account authentication failed")
            assistant = DMAssistant(
                owner.id, config.allowed_user_ids, config.send_enabled,
                LLMClient(config.llm_base_url, config.llm_api_key, config.llm_model), store,
                allow_all=config.allow_all,
            )
            client.add_event_handler(
                assistant.handle, events.NewMessage(incoming=True, func=lambda event: event.is_private)
            )
            await client.run_until_disconnected()
        finally:
            await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in personal Telegram DM draft assistant")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate config offline; no network calls")
    mode.add_argument("--run", action="store_true", help="connect to Telegram and listen for DMs")
    args = parser.parse_args(argv)
    load_dotenv(override=False)
    try:
        config = Config.from_env()
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if args.check:
        print("Configuration valid. No network connection made.")
        return 0
    asyncio.run(run(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
