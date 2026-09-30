# telegram-dm-assistant

A standalone local Telegram **owner-account** DM assistant using Telethon. By default it writes generated replies to a private SQLite draft database; it does **not** send messages. No tasks, groups, channels, bot commands, or background service are included.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and run `uv sync --dev` from this directory (Python 3.11+).
2. Copy `.env.example` to `.env`. Get your **own** Telegram API ID/hash from [my.telegram.org](https://my.telegram.org). Set `TG_API_ID` and `TG_API_HASH` locally. This is a user session, **not** a bot token. Never commit the session file, API hash, or LLM key.
3. Choose `LLM_BACKEND=openrouter` or `openai`; set `LLM_API_KEY` and `LLM_MODEL` for your own account. Defaults: OpenRouter `https://openrouter.ai/api/v1` or OpenAI `https://api.openai.com/v1`; `LLM_BASE_URL` can override with an HTTPS OpenAI-compatible endpoint. DMs are sent to this LLM provider for drafting, even in draft-only mode. Do not use this tool for sensitive conversations without the correspondent's knowledge/consent.
4. Opt in individual **numeric Telegram user IDs** using `DM_ALLOWED_USER_IDS=123456,789012`. Empty means nothing is processed. Keep `DM_SEND_ENABLED=false` until you intentionally choose otherwise. Do not copy a bot token or an unrelated session into this project.
5. Run `uv run telegram-dm-assistant --check` to validate configuration **offline**; it does not construct or connect a Telegram client, contact the LLM, or reveal keys. Then, **only when ready to listen**, run `uv run telegram-dm-assistant --run`. The first run may prompt for login code/2FA interactively and creates a local Telethon `data/owner.session`. No listener starts merely from importing or checking.

Drafts are stored at `data/drafts.sqlite3` (or `$DM_DATA_DIR/drafts.sqlite3`) and may contain sensitive message content. The data directory must have mode 0700 and the draft database mode 0600. Session and data files are ignored by Git. Inspect drafts with a local SQLite reader; they are never sent automatically. To deliberately enable automatic replies, set **both** `DM_SEND_ENABLED=true` and a nonempty allowlist, then explicitly start `--run`. This sends LLM-generated text as your account; review the risk before enabling. Stop with Ctrl-C.

The listener only handles newly received private messages from allowlisted human users (not your own account, bots, outbound messages, or other chats). Per-user locks and a persistent message-ID reservation reduce duplicates across restarts. Reservations are at-most-once: a failed LLM request or Telegram send is **not** retried automatically; inspect logs and handle manually. Only the incoming text (capped at 8,000 characters) is passed to the LLM. No historical chats are fetched. Generated replies are limited to 3,500 UTF-16 code units.

## Offline verification

```bash
uv sync --dev
uv run pytest -q
uv run ruff check .
uv run telegram-dm-assistant --help
```

Tests use only in-memory fake messages and a fake Telegram client; no live sends or LLM API calls. Never run `--run` in CI or during offline verification.
