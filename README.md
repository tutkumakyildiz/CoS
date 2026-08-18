# CoS

Household chief-of-staff Telegram bot, built on the [Strands Agents SDK](https://strandsagents.com/). See [`CoS-agent-design-spec.md`](CoS-agent-design-spec.md) for the full design — this README is just setup + status.

## What's built (Week 1 + a bit of Week 2)

- Strands `Agent` wired to Claude via the **Anthropic API** directly (`src/cos/agent.py`) — spec §2 says Bedrock; see "Design deviations" below for why this starts on the direct API instead.
- `task_store` tool, backed by **SQLite** (`src/cos/tools/task_store.py`, `src/cos/db.py`) — spec §3/§4.1 called for Google Sheets; SQLite is now the permanent choice for this project, not a stand-in (see "Design deviations" below). Includes `get_due_soon_tasks` alongside `get_overdue_tasks` for the nudge scheduler.
- `telegram_tools` (`send_message`, `ask_choice`) — spec §4.4, built on `python-telegram-bot` instead of the community `strands-telegram` package.
- Telegram long-poll listener + callback-query routing (`src/cos/telegram_bot/bot.py`) — spec §4.5, same package-choice reasoning.
- **Daily nudge scheduler** — `telegram_bot/bot.py` registers a `JobQueue.run_daily` job (needs the `python-telegram-bot[job-queue]` extra) that runs the FOLLOW-UP behavior on a schedule (default 9am, configurable via `COS_NUDGE_HOUR`/`COS_TIMEZONE`). Nudges post in the shared group chat addressed to the owner by name, not a private DM — a deliberate, permanent MVP scope decision, not a gap to fill later. See "Design deviations" below.
- **On-demand queries** — partners can ask CoS about tasks any time ("what should I get from the market", "what's on my list"), not just at scheduled check-ins; steered entirely via the system prompt's new ON-DEMAND QUERIES section, using the existing `get_open_tasks` tool.
- **Natural-language task completion** — a plain mention like "I bought milk" (not just the nudge's "Done" button) gets matched against `get_open_tasks` and closed via `mark_done`; ambiguous matches get an `ask_choice` disambiguation, no match gets a brief "didn't find that" reply, and a single clear match always gets a brief confirmation. Steered by the new COMPLETION VIA NATURAL LANGUAGE system-prompt section (`src/cos/prompts.py`).
- `calendar_tool` — spec §4.2, **stubbed**: always reports "not connected." Real Google Calendar wiring is Week 2.
- System prompt from spec §5, plus a household-context block (partner names/ids, numbered `Partner 1`/`Partner 2` role tags for `ask_choice` button labels) and a note that `send_message`/`ask_choice` are the agent's *only* reply channel.
- End-to-end capture → confirm → ask-ownership-via-buttons → assign loop works (this pulls the Week-2 "ownership inline keyboards" item forward since it's what makes the MVP demoable).

**Not yet built** (still Week 2/3 per the spec's build order): weekly `digest_generator` + scheduler, real calendar integration, metrics logging. (Private DM nudges and a Google Sheets migration were both in the original spec's later-weeks scope but are now explicitly out of scope for this MVP — see "Design deviations" below.)

**Status as of 2026-08-18:** ran a live end-to-end test in the real household group chat (chat_id configured, both partners' user ids in `household.json`). Capture → confirm → ask-ownership buttons → tap → owner-assigned all worked. Found and fixed a bug along the way: the agent had no notion of the real current date, so relative dates ("before September") resolved against training data instead of the actual calendar — fixed by prefixing every message/callback instruction with today's date in `telegram_bot/bot.py` (`_today_prefix()`).

Personalized `ask_choice` button labels and on-demand queries are now **live-tested and confirmed working**: ownership prompts show exactly 3 buttons (`Assign to {name}` per partner + `Split - let's talk`, no stray "I'll take it", no role tags) and a grocery-style on-demand question gets a sane reply. Getting there took two live-testing rounds of fixes — first removing an unwanted `(Partner N)` role tag suffix, then removing an extra "I'll take it" button and a hardcoded "Assign to Sam" example in the `ask_choice` tool's own docstring that was likely biasing the model off the real names.

The daily nudge's one-tap "Done" button and natural-language completion (e.g. "I bought milk") are both now **live-tested and confirmed working** — a task can be closed either way.

**Model swapped to `claude-haiku-4-5` (2026-08-18)**, down from `claude-sonnet-4-5-20250929`, for cost — Haiku is ~5x cheaper on both input and output and the bot's per-turn workload (short capture/confirm/ownership replies, on-demand queries) doesn't need Sonnet-tier reasoning. Updated in `.env`, `.env.example`, and the fallback default in `config.py`. Verified via the unit test suite, a direct Anthropic API call against the new model id, and a live bot run in the real household group chat — no regressions.

## Design deviations from the spec (and why)

| Spec said | Built instead | Why |
|---|---|---|
| Claude via Amazon Bedrock | Claude via Anthropic API (`strands.models.anthropic.AnthropicModel`) | No AWS/Bedrock access configured yet. Swapping back is a ~5-line change in `agent.py` (construct a `BedrockModel` instead) — Strands abstracts the model provider, nothing else changes. |
| `strands-telegram` / `strands-telegram-listener` (community packages) | `python-telegram-bot` directly, wrapped in custom Strands tools | The spec itself (§8) flags these as unreviewed community packages and names this exact fallback. Went straight there rather than vetting the community packages first. |

**Decided (not just deferred) — permanent MVP scope, per the user 2026-08-18:**
- **SQLite stays.** Originally framed as a temporary stand-in for the spec's Google Sheets persistence (§3/§4.1/§8). The user decided to keep SQLite for good rather than migrate — it's no longer an open item, so there's no pending Sheets swap.
- **Nudges stay in the shared group chat, addressed to the owner by name — no private DMs.** Originally framed as a temporary workaround (spec §5 FOLLOW-UP asked for a DM) because Telegram requires a user to `/start` a bot privately before it can DM them. The user decided against private DM nudges for the MVP outright, so this isn't pending either.

## Setup

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Get a Telegram bot token

1. Open a chat with [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot`, give it a name and a username (must end in `bot`, e.g. `OurHouseholdCoSBot`).
3. BotFather replies with a token like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` — that's `TELEGRAM_BOT_TOKEN`.
4. Create (or use) your household's Telegram **group chat** and add the bot to it.
5. In **group** settings, turn the bot's **admin** status on *or* disable **Group Privacy** for it via BotFather (`/mybots` → your bot → *Bot Settings* → *Group Privacy* → *Turn off*) — otherwise Telegram only forwards messages that start with `/command` or `@mention` the bot, and CoS needs to see every message to do capture.

### 3. Get the group chat's `chat_id`

Easiest way once the bot is in the group:
1. Send any message in the group.
2. Visit `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates` in a browser (substitute your real token).
3. Find `"chat":{"id": -1001234567890, ...}` in the JSON — group chat ids are negative numbers. That's your `chat_id`.

### 4. Configure

```bash
cp .env.example .env
cp household.example.json household.json
```

Fill in `.env`:
- `TELEGRAM_BOT_TOKEN` — from step 2
- `ANTHROPIC_API_KEY` — from https://console.anthropic.com/settings/keys
- `COS_MODEL_ID` — a current Claude model id (default in `.env.example` may drift; check [docs.anthropic.com](https://docs.anthropic.com) for the current one)

Fill in `household.json`:
```json
{
  "chat_id": "-1001234567890",
  "partners": {
    "111111111": "Alex",
    "222222222": "Sam"
  }
}
```
`chat_id` from step 3. The two keys under `partners` are each partner's Telegram **user id** (not username) mapped to a display name — get a user's numeric id by having them message [@userinfobot](https://t.me/userinfobot).

### 5. Run

```bash
python -m cos.main
```

This starts the long-polling listener. Post a task-shaped message in the group ("we need to book Mia's dentist appointment") and CoS should capture it and ask who owns it.

### 6. Tests

```bash
pytest
```

Covers `task_store` against a throwaway SQLite db — no Telegram/Anthropic credentials needed.

## Project layout

```
src/cos/
  config.py           # env + household.json loading
  db.py                # sqlite schema (tasks, digest_log)
  agent.py             # builds the one Strands Agent, per chat_id
  prompts.py           # system prompt (spec §5) + household context
  main.py              # entry point
  tools/
    task_store.py       # spec §4.1
    telegram_tools.py    # spec §4.4 (send_message, ask_choice)
    calendar_tool.py     # spec §4.2 (stub)
  telegram_bot/
    bot.py              # long-poll listener + callback routing, spec §4.5
tests/
  test_task_store.py
  test_bot.py
```

## Next up

- **Queued (do first): live-test the daily nudge scheduler** — button labels and on-demand queries are already confirmed live-working (see Status above). The nudge scheduler is the one piece still unverified against the real bot: restart with `python -m cos.main`, let it run past the configured hour (`COS_NUDGE_HOUR`, default 9am local), and confirm a nudge posts in-chat addressed to the right owner with a working one-tap "Done" button.

Week 2/3, per spec §7:
- `digest_generator` tool + weekly digest scheduler
- Real Google Calendar wiring in `calendar_tool.py`
- Basic metrics logging (tasks captured, resolved-without-follow-up, delegation acceptance rate)

Out of scope for this MVP (deliberate, see "Design deviations"): private DM nudges, Google Sheets migration.
