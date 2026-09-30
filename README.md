# telegram-dm-assistant

A standalone local Telegram **owner-account** DM assistant using Telethon. By default it writes generated replies to a private SQLite draft database; it does **not** send messages. No tasks, groups, channels, bot commands, or background service are included.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync --dev` from this directory (Python 3.11+).
2. Copy `.env.example` to `.env`. Get your **own** Telegram API ID/hash from [my.telegram.org](https://my.telegram.org). Set `TG_API_ID` and `TG_API_HASH` locally. This is a user session, **not** a bot token. Never commit the session file, API hash, or LLM key.
3. Choose `LLM_BACKEND=openrouter` or `openai`; set `LLM_API_KEY` and `LLM_MODEL` for your own account. Defaults: OpenRouter `https://openrouter.ai/api/v1` or OpenAI `https://api.openai.com/v1`; `LLM_BASE_URL` can override with an HTTPS OpenAI-compatible endpoint. DMs are sent to this LLM provider for drafting, even in draft-only mode. Do not use this tool for sensitive conversations without the correspondent's knowledge/consent.
4. For selected people, use numeric IDs in `DM_ALLOWED_USER_IDS=123456,789012`. Empty means nothing is processed unless `DM_ALLOW_ALL=true` is explicitly set. To answer **every incoming human private DM**, set `DM_ALLOW_ALL=true` and `DM_SEND_ENABLED=true`. This sends LLM-generated replies from your account to people who message you; it excludes your own messages, bots, and groups. Keep both false until intentionally activating. Do not copy a bot token into this project.
5. Run `uv run telegram-dm-assistant --check` to validate configuration **offline**. If Telegram login is needed, run `uv run telegram-dm-assistant --login` in your own interactive terminal and enter the login code/2FA there (never in chat); this only authenticates and creates the private `data/owner.session`, without listening or sending. Then run `uv run telegram-dm-assistant --run` to listen. No listener starts merely from importing, checking, or logging in.

Drafts are stored at `data/drafts.sqlite3` (or `$DM_DATA_DIR/drafts.sqlite3`) and may contain sensitive message content. The data directory must have mode 0700 and the draft database mode 0600. Session and data files are ignored by Git. Inspect drafts with a local SQLite reader; they are never sent automatically. To deliberately enable automatic replies, set `DM_SEND_ENABLED=true` together with either a nonempty allowlist or `DM_ALLOW_ALL=true`, then explicitly start `--run`. Stop with Ctrl-C.

The listener only handles newly received private messages from allowed human users, or all human DM senders when explicitly enabled (not your own account, bots, outbound messages, or groups). Per-user locks and a persistent message-ID reservation reduce duplicates across restarts. Reservations are at-most-once: a failed LLM request or Telegram send is **not** retried automatically; inspect logs and handle manually. Only the incoming text (capped at 8,000 characters) is passed to the LLM. No historical chats are fetched. Generated replies are limited to 3,500 UTF-16 code units.

## Offline verification

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
uv run telegram-dm-assistant --help
```

Tests use only in-memory fake messages and a fake Telegram client; no live sends or LLM API calls. Never run `--run` in CI or during offline verification.
