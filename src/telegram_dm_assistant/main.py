"""Explicit CLI entry point; --check never connects to Telegram or the LLM."""

import argparse
import asyncio

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import User

from .assistant import DMAssistant, DraftStore
from .config import Config
from .history import HistoryImporter
from .llm import LLMClient


async def login(config: Config) -> None:
    """Authenticate interactively without registering a DM listener."""
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if config.data_dir.stat().st_mode & 0o077:
        raise PermissionError("Data directory must be private (chmod 700)")
    client = TelegramClient(str(config.data_dir / "owner"), config.api_id, config.api_hash)
    try:
        await client.start()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram login failed")
        print("Telegram session authorized; listener not started.")
    finally:
        await client.disconnect()


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
                LLMClient(config.llm_base_url, config.llm_api_key, config.llm_model,
                          reply_as_owner=config.reply_as_owner), store,
                allow_all=config.allow_all,
                excluded_ids=config.excluded_user_ids,
                context_enabled=config.context_enabled, client=client,
            )
            client.add_event_handler(
                assistant.handle, events.NewMessage(incoming=True, func=lambda event: event.is_private)
            )
            if config.context_enabled:
                client.add_event_handler(
                    assistant.handle_outgoing,
                    events.NewMessage(outgoing=True, func=lambda event: event.is_private),
                )
            await client.run_until_disconnected()
        finally:
            await client.disconnect()


async def backfill(config: Config, chat_id: int | None = None) -> int:
    """Read-only history import; counts only, no handlers, model, or sending."""
    config.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    imported = skipped = failed = messages = 0
    with DraftStore(config.data_dir / "drafts.sqlite3") as store:
        client = TelegramClient(str(config.data_dir / "owner"), config.api_id, config.api_hash)
        try:
            await client.start()
            owner = await client.get_me()
            if owner is None:
                raise RuntimeError("Account unavailable")
            importer = HistoryImporter(client, store, owner.id, config.allowed_user_ids,
                                       config.allow_all, config.excluded_user_ids)

            async def ingest(peer, entity=None):
                nonlocal imported, skipped, failed, messages
                if (not importer.eligible_id(peer) or (entity is not None and
                        (not isinstance(entity, User) or entity.bot or entity.deleted))):
                    skipped += 1
                    return
                try:
                    messages += await importer.ensure(peer)
                    if peer in importer.synced:
                        imported += 1
                    else:
                        skipped += 1
                except Exception:  # noqa: BLE001 - isolate failed chats without leaking content
                    failed += 1  # Never print exception text or private dialog metadata.

            if chat_id is not None:
                await ingest(chat_id)
            else:
                async for dialog in client.iter_dialogs():
                    await ingest(dialog.id, dialog.entity)
        except Exception:  # noqa: BLE001 - counts-only CLI failure contract
            failed += 1
        finally:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 - do not leak disconnect error contents
                failed += 1
    print(f"Imported chats: {imported}; skipped: {skipped}; failed: {failed}; messages: {messages}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opt-in personal Telegram DM draft assistant")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="validate config offline; no network calls")
    mode.add_argument("--login", action="store_true", help="authenticate interactively; do not listen")
    mode.add_argument("--run", action="store_true", help="connect to Telegram and listen for DMs")
    mode.add_argument("--backfill", action="store_true", help="import eligible private history only")
    parser.add_argument("--chat-id", type=int, help="restrict --backfill to one positive user ID")
    args = parser.parse_args(argv)
    if args.chat_id is not None and (not args.backfill or args.chat_id <= 0):
        parser.error("--chat-id requires --backfill and a positive user ID")
    load_dotenv(override=False)
    try:
        config = Config.from_env()
    except (ValueError, KeyError) as exc:
        parser.error(str(exc))
    if args.check:
        print("Configuration valid. No network connection made.")
        return 0
    if args.login:
        asyncio.run(login(config))
        return 0
    if args.backfill:
        return asyncio.run(backfill(config, args.chat_id))
    asyncio.run(run(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
