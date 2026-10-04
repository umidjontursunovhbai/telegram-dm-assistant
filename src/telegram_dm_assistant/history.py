"""Lazy, read-only, resumable history ingestion; never sends or calls a model."""

import asyncio

from telethon.errors import FloodWaitError
from telethon.tl.types import User


def message_text(message):
    return getattr(message, "raw_text", None) or "[unsupported media or service message]"


def reply_to_id(message):
    """Telethon exposes the pointer on either the event or its Message wrapper."""
    pointer = getattr(message, "reply_to_msg_id", None)
    if pointer is None:
        pointer = getattr(getattr(message, "message", None), "reply_to_msg_id", None)
    return pointer if isinstance(pointer, int) and not isinstance(pointer, bool) and pointer > 0 else None


class HistoryImporter:
    def __init__(self, client, store, owner_id, allowed_ids, allow_all=False,
                 excluded_ids=frozenset(), concurrency=2, sleep=asyncio.sleep):
        self.client, self.store, self.owner_id = client, store, owner_id
        self.allowed_ids, self.allow_all = allowed_ids, allow_all
        self.excluded_ids = excluded_ids
        self.semaphore = asyncio.Semaphore(concurrency)
        self.sleep = sleep
        self.synced = set()
        self.locks = {}

    def eligible_id(self, peer):
        return (isinstance(peer, int) and peer > 0 and peer != self.owner_id
                and peer not in self.excluded_ids
                and (self.allow_all or peer in self.allowed_ids))

    async def ensure(self, peer):
        if not self.eligible_id(peer):
            return 0
        async with self.locks.setdefault(peer, asyncio.Lock()):
            if peer in self.synced:
                return 0
            async with self.semaphore:
                for attempt in range(3):
                    try:
                        entity = await self.client.get_entity(peer)
                        if (not isinstance(entity, User) or entity.bot or entity.deleted
                                or entity.id != peer):
                            return 0
                        count = await self._ingest(entity)
                        self.synced.add(peer)
                        return count
                    except FloodWaitError as exc:
                        if attempt == 2 or exc.seconds > 60:
                            raise
                        await self.sleep(exc.seconds)
        return 0

    async def _ingest(self, entity):
        peer = entity.id
        last, _ = self.store.checkpoint(self.owner_id, peer)
        self.store.set_checkpoint(self.owner_id, peer, last, complete=False)
        count = 0
        async for message in self.client.iter_messages(
            entity, reverse=True, limit=None, min_id=last,
        ):
            self.store.record(self.owner_id, peer, message.id, message.date,
                              "owner" if message.out else "incoming", message_text(message),
                              reply_to_id=reply_to_id(message))
            last = max(last, message.id)
            self.store.set_checkpoint(self.owner_id, peer, last, complete=False)
            count += 1
        self.store.set_checkpoint(self.owner_id, peer, last, complete=True)
        return count
