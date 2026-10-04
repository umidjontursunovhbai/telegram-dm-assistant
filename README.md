# Telegram DM Assistant

A personal assistant for your Telegram inbox. It replies to people who DM your account, using AI to answer simple questions or ask for details when something needs your decision. By default it speaks as your assistant, not as you. An explicit owner-voice option can instead draft first-person replies on your authorized behalf using your prior messages in that same chat. It doesn't create tasks, read groups or channels, or require people to message a bot.

You choose how it behaves:

- **Draft mode:** save a suggested reply locally without sending it. This is the default.
- **Auto-reply mode:** send the suggested reply from your account, either to selected people or to anyone who sends you a private message.

The assistant starts with new text DMs after you turn it on. It never replies to your own messages, bots, groups, channels, or old chat history. Optional persistent context can read eligible DM history without replying to it. Each incoming message is handled at most once; if a reply fails, it won't retry on its own.

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

## Optional persistent DM context

`DM_CONTEXT_ENABLED=false` is the default. With it disabled, replies use only the
new incoming message and there is no history import or outgoing-message handler.
Opt in separately for each account; do **not** turn it on in a shared `.env` if
another listener must stay unchanged. Separate accounts require separate
`DM_DATA_DIR` directories and Telegram sessions. Set `DM_EXCLUDED_USER_IDS` to
all other managed account IDs on every listener to prevent assistant reply loops;
exclusions override both allow-all and allowlists.

When enabled, the listener lazily imports the eligible conversation's full
available history before its first reply in each process. It also stores new
incoming messages, manual outgoing messages, and sent assistant replies using
Telegram's actual message IDs. Draft suggestions are not treated as sent replies.
Bots, deleted users, Saved Messages, excluded accounts, groups and channels are
not imported. Eligibility follows `DM_ALLOWED_USER_IDS` / `DM_ALLOW_ALL`.
Unsupported media and service messages get a placeholder; media is not downloaded.
Old imported messages never go through the auto-reply handler.

To import all eligible existing private human dialogs **without starting a
listener, creating a model client, or sending anything**, use `--backfill`.
`--chat-id` optionally restricts it to one positive user ID. Authenticate with
`--login` first. Stop the corresponding listener while importing; do not run two
clients against the same account/session at once. For a separately authenticated
second account, explicit process-local settings look like this:

```bash
DM_DATA_DIR=data-account-2 DM_CONTEXT_ENABLED=true uv run telegram-dm-assistant --backfill
# Optional one-chat import (replace the placeholder numeric ID):
DM_DATA_DIR=data-account-2 DM_CONTEXT_ENABLED=true uv run telegram-dm-assistant --backfill --chat-id 123456
```

Backfill is explicit even if context is disabled; the flag only gates live
listener behavior. Output contains counts only: imported chats, skipped dialogs,
failed chats/operations, and messages from completed imports. Failed chats do not
stop other dialogs; any failure returns exit status 1. Retry the same command to
resume. Messages already saved before a failure remain stored even though that
failed import's message count is not included in the summary. Checkpoints advance
after each saved message, mark complete only after iterator exhaustion, and scan
newer messages on the next backfill/process start. Import is sequential for the
CLI and bounded to two simultaneous imports in the live listener. Flood waits up
to 60 seconds are retried at most twice; longer/exhausted waits fail safely.

Full available text history is saved locally in `drafts.sqlite3`, keyed by owner,
chat, and message ID. **The model receives only a bounded subset**, never the
whole database: up to four earliest baseline turns, eight most recent
owner-authored style examples, twelve recent turns, and twelve keyword-ranked
historical turns, deduplicated and ordered chronologically. Owner examples have
reserved space even when recent conversation is dominated by automated replies. Text
copies total at most 16,000 characters, plus labels/metadata and the current
message (at most 8,000 characters). Unicode casefold supports Cyrillic keyword
matching as well as English/Uzbek. This is heuristic retrieval, not guaranteed
recall of every old detail. SQL queries stay owner/chat scoped; no other
conversation's history is included. SQLite uses WAL with `synchronous=NORMAL`
and a 30-second lock timeout so history readers do not block behind every
per-message disk flush. This protects database consistency, but the newest
transactions can be lost on a hard power failure; a later import can restore
Telegram history (not a guarantee against duplicate replies after such a failure).
History is untrusted evidence: the prompt
adapts style, language and formality without impersonating you in default assistant
mode or treating old statements as current commitments in either mode.

## Optional authorized owner voice

`DM_REPLY_AS_OWNER=false` is the safe default; existing assistant identity stays
unchanged. Set it to `true` only with the account owner's explicit authorization.
It requires `DM_CONTEXT_ENABLED=true`; startup rejects owner voice without context.
Use process/service-local settings for the authorized account, **not a shared
`.env`** when another account must remain disabled or unchanged. The flags do not
change send permissions: keep `DM_SEND_ENABLED=false` to review local drafts first.

In owner mode, the model is asked to write a ready-to-send first-person reply on
Umidjon's behalf, without an assistant introduction or third-person owner wording.
Style evidence comes only from historical `kind=owner` messages in **this chat**,
not the other person's messages or stored `kind=assistant` outputs. New automated
replies remain labeled `assistant` even in owner mode, so they do not train the
next reply's voice. The prompt mirrors evidenced brevity, formality, language,
script, slang, punctuation, emojis, nicknames and intimacy without escalating the
relationship. Missing owner examples mean neutral, concise wording, not an invented
persona. Missing facts should lead to a short natural clarification, not invented
location, availability, actions, promises or decisions. A direct question about
automation must be answered honestly; owner voice is not permission to deny it.

This is **bounded examples-based prompting, not a learned per-person persona or a
guarantee of matching style**. Imported outgoing history is classified as owner
unless already stored as an assistant reply; externally generated outgoing text
cannot be reliably distinguished from manual text. Review the examples and drafts
where historical outgoing messages may include outside automation. Historical and
incoming text remains untrusted evidence, never instructions overriding these
limits. A detected ChatGPT self-identification fails closed in owner mode instead
of inserting the default assistant fallback; that message gets no reply or draft
and is not automatically retried. Prompt constraints cannot guarantee every
provider output is safe or accurate. Test the configured provider with synthetic
examples without Telegram sending before enabling the authorized listener.

## Where do drafts go?

Drafts are saved in `data/drafts.sqlite3` on your machine (or under `DM_DATA_DIR` if you set it). This is a local SQLite file, **not a Telegram draft** that appears in the app. There is no review-and-send screen yet. To read drafts, use a local SQLite viewer. The Telegram login session is stored in `data/owner.session`; keep both files private and back them up carefully. Neither is committed to Git.

## Privacy and limits

To write a reply, the assistant sends the incoming message text to your configured AI provider. Avoid using it for sensitive conversations unless the other person understands that their message may be processed by an AI service. By default it sees only the current message. With context enabled, selected past messages from that same conversation are also sent to the configured provider; this includes your own messages. It does not see your calendar, tasks, or other chats. It cannot make decisions or take actions for you. Only new text DMs are handled; media-only messages are skipped. Replies can be wrong or inappropriate, so use draft mode or restrict the allowlist if you want more control. Failed replies are not automatically retried.

## For contributors

Run the offline checks with `uv sync --dev`, `uv run pytest -q`, and `uv run ruff check .`. Tests use fake Telegram events and do not send messages.
