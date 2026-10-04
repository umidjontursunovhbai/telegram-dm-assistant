"""Owner/chat-scoped persistent Telegram history, independent of reply reservations."""

import re
from datetime import UTC


class ConversationContext(list):
    """List-compatible bounded turns with optional unavailable reply-target metadata."""

    def __init__(self, turns, reply_to_id=None):
        super().__init__(turns)
        self.reply_to_id = reply_to_id


class ConversationStore:
    def init_memory(self):
        self.db.create_function("unicode_fold", 1, str.casefold, deterministic=True)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                owner_id INTEGER, chat_id INTEGER, message_id INTEGER,
                date TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
                PRIMARY KEY(owner_id, chat_id, message_id));
            CREATE TABLE IF NOT EXISTS history_state (
                owner_id INTEGER, chat_id INTEGER, last_id INTEGER NOT NULL,
                complete INTEGER NOT NULL, PRIMARY KEY(owner_id, chat_id));
        """)

        columns = {row[1] for row in self.db.execute("PRAGMA table_info(messages)")}
        if "reply_to_id" not in columns:
            with self.db:
                self.db.execute("ALTER TABLE messages ADD COLUMN reply_to_id INTEGER")

    def record(self, owner, chat, mid, date, kind, text, reply_to_id=None):
        if kind not in {"incoming", "owner", "assistant"}:
            raise ValueError("Invalid message kind")
        stamp = date.replace(tzinfo=date.tzinfo or UTC).astimezone(UTC).isoformat()
        with self.db:
            self.db.execute(
                "INSERT INTO messages "
                "(owner_id, chat_id, message_id, date, kind, text, reply_to_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(owner_id, chat_id, message_id) DO UPDATE SET "
                "text=excluded.text, date=excluded.date, "
                "reply_to_id=COALESCE(excluded.reply_to_id, messages.reply_to_id), "
                "kind=CASE WHEN messages.kind='assistant' THEN 'assistant' ELSE excluded.kind END",
                (owner, chat, mid, stamp, kind, text or "", reply_to_id),
            )

    def messages(self, owner, chat):
        rows = self.db.execute(
            "SELECT message_id, date, kind, text, reply_to_id FROM messages "
            "WHERE owner_id=? AND chat_id=? ORDER BY date, message_id", (owner, chat),
        ).fetchall()
        return [dict(zip(("id", "date", "kind", "text", "reply_to_id"), row)) for row in rows]

    def context(self, owner, chat, query, before_id, budget=16000, reply_to_id=None):
        """Bound scoped style/recent turns and chronological windows around recall/target hits."""
        budget = max(0, min(budget, 16000))
        base = ("SELECT message_id, date, kind, text, reply_to_id FROM messages "
                "WHERE owner_id=? AND chat_id=? AND message_id<? ")
        args = (owner, chat, before_id)
        first = self.db.execute(base + "ORDER BY date, message_id LIMIT 4", args).fetchall()
        recent = self.db.execute(
            base + "ORDER BY date DESC, message_id DESC LIMIT 12", args,
        ).fetchall()
        owner_style = self.db.execute(
            base + "AND kind='owner' ORDER BY date DESC, message_id DESC LIMIT 8", args,
        ).fetchall()
        tokens = sorted(set(re.findall(r"[^\W_]{3,}", query.casefold())))[:12]
        relevant = []
        if tokens:
            score = " + ".join("(instr(unicode_fold(text), ?) > 0)" for _ in tokens)
            relevant = self.db.execute(
                base + f"AND ({score}) > 0 ORDER BY ({score}) DESC, "
                "date DESC, message_id DESC LIMIT 12",
                (*args, *tokens, *tokens),
            ).fetchall()
        target = self.db.execute(
            base + "AND message_id=?", (*args, reply_to_id),
        ).fetchall() if reply_to_id is not None else []
        neighbors = {}
        for anchor in [*target, *relevant]:
            mid, date = anchor[:2]
            for direction, order in (("<=", "DESC"), (">", "ASC")):
                rows = self.db.execute(
                    base + f"AND (date, message_id) {direction} (?, ?) "
                    f"ORDER BY date {order}, message_id {order} LIMIT 3",
                    (*args, date, mid),
                ).fetchall()
                for row in rows:
                    neighbors[row[0]] = row
        relevant = list(neighbors.values())
        selected = {}
        # Reserve space for each source; truncate only prompt copies, never stored history.
        recall_share = budget // 4 if target else budget * 3 // 8
        for rows, share in ((first, budget // 8), (owner_style, budget // 4),
                            (relevant, recall_share), (recent, budget // 4),
                            (target, budget // 8)):
            per_turn = share // max(len(rows), 1)
            for mid, date, kind, text, pointer in rows:
                old = selected.get(mid)
                candidate = {"id": mid, "date": date, "kind": kind, "text": text[:per_turn],
                             "reply_to_id": pointer}
                if old is None or len(candidate["text"]) > len(old["text"]):
                    selected[mid] = candidate
                if mid in neighbors:
                    selected[mid]["relevant_neighbor"] = True
        recent_ids = {row[0] for row in recent}
        for mid, turn in selected.items():
            if mid in recent_ids:
                turn["recent_exchange"] = True
            if target and mid == reply_to_id:
                turn["direct_reply_target"] = True
        return ConversationContext(
            sorted(selected.values(), key=lambda row: (row["date"], row["id"])), reply_to_id,
        )

    def checkpoint(self, owner, chat):
        row = self.db.execute(
            "SELECT last_id, complete FROM history_state WHERE owner_id=? AND chat_id=?",
            (owner, chat),
        ).fetchone()
        return (row[0], bool(row[1])) if row else (0, False)

    def set_checkpoint(self, owner, chat, last_id, complete=False):
        with self.db:
            self.db.execute(
                "INSERT INTO history_state VALUES (?, ?, ?, ?) "
                "ON CONFLICT(owner_id, chat_id) DO UPDATE SET "
                "last_id=MAX(history_state.last_id, excluded.last_id), complete=excluded.complete",
                (owner, chat, last_id, int(complete)),
            )
