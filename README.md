# Telegram DM Assistant

A personal assistant for your Telegram inbox. It replies to people who DM your account, using AI to answer simple questions or ask for details when something needs your decision. It speaks as your assistant, not as you. It doesn't create tasks, read groups or channels, or require people to message a bot.

You choose how it behaves:

- **Draft mode:** save a suggested reply locally without sending it. This is the default.
- **Auto-reply mode:** send the suggested reply from your account, either to selected people or to anyone who sends you a private message.

The assistant starts with new text DMs after you turn it on. It ignores your own messages, bots, groups, channels, and old chat history. Each incoming message is handled at most once; if a reply fails, it won't retry on its own.

## Get started

You'll need Python 3.11+, [uv](https://docs.astral.sh/uv/), a Telegram API ID and hash from [my.telegram.org](https://my.telegram.org), and an OpenRouter or OpenAI API key.

```bash
uv sync
cp .env.example .env
```

Open `.env` and fill in `TG_API_ID`, `TG_API_HASH`, `LLM_API_KEY`, and `LLM_MODEL`. The default AI provider is OpenRouter; set `LLM_BACKEND=openai` if you use OpenAI instead. The `.env` file stays on your machine and is ignored by Git.

Pick who the assistant can answer:

```env
# To reply only to selected people (use their numeric Telegram user IDs):
DM_ALLOWED_USER_IDS=123456,789012

# Or, to reply to any human who sends your account a private DM:
DM_ALLOW_ALL=true
```

For drafts, leave `DM_SEND_ENABLED=false`. To actually send replies, set `DM_SEND_ENABLED=true` **and** choose an allowlist or `DM_ALLOW_ALL=true`. The assistant sends as *you*, so check this setting before starting it.

Then run:

```bash
uv run telegram-dm-assistant --check  # Check settings without connecting
uv run telegram-dm-assistant --login  # One-time Telegram login
uv run telegram-dm-assistant --run    # Listen for new DMs
```

Enter your Telegram login code or 2FA password only in your own terminal, never in chat or GitHub. `--login` does not listen or reply. Stop a foreground listener with Ctrl-C. If you run it as a service, stop that service instead; don't start a second copy alongside it.

## Where do drafts go?

Drafts are saved in `data/drafts.sqlite3` on your machine (or under `DM_DATA_DIR` if you set it). This is a local SQLite file, **not a Telegram draft** that appears in the app. There is no review-and-send screen yet. To read drafts, use a local SQLite viewer. The Telegram login session is stored in `data/owner.session`; keep both files private and back them up carefully. Neither is committed to Git.

## Privacy and limits

To write a reply, the assistant sends the incoming message text to your configured AI provider. Avoid using it for sensitive conversations unless the other person understands that their message may be processed by an AI service. It sees only the current message, not your calendar, tasks, other chats, or past messages. It cannot make decisions or take actions for you. Only new text DMs are handled; media-only messages are skipped. Replies can be wrong or inappropriate, so use draft mode or restrict the allowlist if you want more control. Failed replies are not automatically retried.

## For contributors

Run the offline checks with `uv sync --dev`, `uv run pytest -q`, and `uv run ruff check .`. Tests use fake Telegram events and do not send messages.
