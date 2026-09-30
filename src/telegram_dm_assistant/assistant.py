"""Private incoming messages only; persisted at-most-once reservations."""

import asyncio
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .llm import trim_reply


class DraftStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.stat().st_mode & 0o077:
            raise PermissionError("Draft data directory must be private (chmod 700)")
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        if path.stat().st_mode & 0o077:
            raise PermissionError("Draft database must be private (chmod 600)")
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS seen (chat_id INTEGER, message_id INTEGER, "
                        "draft TEXT, PRIMARY KEY(chat_id, message_id))")
        self.db.commit()

    def reserve(self, chat_id: int, message_id: int) -> bool:
        with self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO seen (chat_id, message_id) VALUES (?, ?)",
                (chat_id, message_id),
            )
        return cursor.rowcount == 1

    def save_draft(self, chat_id: int, message_id: int, draft: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE seen SET draft = ? WHERE chat_id = ? AND message_id = ?",
                (draft, chat_id, message_id),
            )

    def drafts(self) -> list[tuple[int, int, str]]:
        return self.db.execute(
            "SELECT chat_id, message_id, draft FROM seen WHERE draft IS NOT NULL "
            "ORDER BY chat_id, message_id"
        ).fetchall()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.db.close()


class DMAssistant:
    def __init__(self, owner_id, allowed_ids, send_enabled, generator, store):
        self.owner_id = owner_id
        self.allowed_ids = allowed_ids
        self.send_enabled = send_enabled
        self.generator = generator
        self.store = store
        self.started = datetime.now(UTC)
        self.locks = {user_id: asyncio.Lock() for user_id in allowed_ids}

    async def handle(self, event) -> None:
        sender_id = event.sender_id
        if (
            event.out or not event.is_private or sender_id is None
            or sender_id == self.owner_id or sender_id not in self.allowed_ids
            or event.chat_id != sender_id or not event.raw_text.strip()
            or event.date.replace(tzinfo=event.date.tzinfo or UTC) < self.started
        ):
            return
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return
        async with self.locks[sender_id]:
            if not self.store.reserve(sender_id, event.id):
                return
            answer = trim_reply(await self.generator.generate(event.raw_text[:8000]))
            if not answer:
                return
            if self.send_enabled:
                await event.reply(answer)
            else:
                self.store.save_draft(sender_id, event.id, answer)
