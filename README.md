# CoS

Household chief-of-staff Telegram bot, built on the [Strands Agents SDK](https://strandsagents.com/). It lives in a shared household group chat, turns loose mentions ("we need to book Mia's dentist appointment") into tracked tasks, asks who's taking each one, follows up so nothing falls through the cracks, and gives a neutral weekly picture of who's carrying what.

See [`CoS-agent-design-spec.md`](CoS-agent-design-spec.md) for the full design rationale.

## Architecture

![CoS agent-invocation path: today vs. hackathon target](docs/architecture.svg)

*Today, the gateway calls a Strands Agent running in-process against the Anthropic API and local SQLite. The hackathon target keeps the same gateway, but routes that call through Amazon Bedrock AgentCore Runtime instead, backed by Amazon Bedrock and DynamoDB. See [`CoS-agent-design-spec.md`](CoS-agent-design-spec.md#8-hackathon-target-architecture-bedrock--agentcore) for the full rationale.*

## Features

- **Capture** — turns natural mentions in the group chat into structured tasks.
- **Delegation** — asks who owns a new task via inline buttons (or "Split — let's talk").
- **Completion** — close a task either by tapping "Done" on a nudge, or just saying so in chat ("I bought milk").
- **Daily nudges** — reminds owners of tasks due soon, posted in the group and addressed to them by name.
- **On-demand queries** — ask CoS what's open any time ("what should I get from the market").
- **Weekly stats** — a neutral summary of tasks captured/completed per partner, and how many were resolved without a reminder. No praise, no blame.
- **Reply safety net** — the agent retries automatically if it silently forgets to send its reply.

## Status

Core MVP is built and live-tested end-to-end in a real household group: capture, delegation, both completion paths, daily nudges, weekly stats, and the reply safety net all work in production use today.

**Not yet built:** real Google Calendar integration (`calendar_tool.py` is currently a stub that always reports "not connected") — the one remaining item from the original design spec's build order.

## Design deviations from the spec

| Spec called for | Built instead | Why |
|---|---|---|
| Claude via Amazon Bedrock | Claude via the Anthropic API directly (`strands.models.anthropic.AnthropicModel`) | No AWS/Bedrock access configured yet. Swapping is a small, isolated change in `agent.py` — Strands abstracts the model provider, nothing else changes. |
| Community `strands-telegram` / `strands-telegram-listener` packages | `python-telegram-bot`, wrapped in custom Strands tools | Spec itself flagged those packages as unreviewed. |
| Google Sheets persistence | SQLite | Kept permanently by design choice — no GCP dependency. |
| Private DM nudges | Nudges posted in the shared group chat, addressed to the owner by name | Avoids requiring each partner to `/start` the bot privately before it can message them. |
| Weekly digest with an imbalance callout | Neutral weekly stats summary, no praise/blame | Narrower, purpose-built replacement — partners can still ask about open tasks any time via on-demand queries. |

## Setup

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Get a Telegram bot token

1. Open a chat with [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot`, give it a name and a username (must end in `bot`).
3. BotFather replies with a token — that's `TELEGRAM_BOT_TOKEN`.
4. Create (or use) your household's Telegram **group chat** and add the bot to it.
5. In BotFather, disable **Group Privacy** for the bot (`/mybots` → your bot → *Bot Settings* → *Group Privacy* → *Turn off*) — otherwise Telegram only forwards `/command` or `@mention` messages, and CoS needs to see every message to do capture.

### 3. Get the group chat's `chat_id`

1. Send any message in the group.
2. Visit `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates` in a browser.
3. Find `"chat":{"id": -1001234567890, ...}` in the JSON — group chat ids are negative numbers.

### 4. Configure

```bash
cp .env.example .env
cp household.example.json household.json
```

Fill in `.env`:
- `TELEGRAM_BOT_TOKEN` — from step 2
- `ANTHROPIC_API_KEY` — from https://console.anthropic.com/settings/keys
- `COS_MODEL_ID` — a current Claude model id

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
`chat_id` from step 3. The keys under `partners` are each partner's Telegram **user id** (not username) mapped to a display name — get a user's numeric id by having them message [@userinfobot](https://t.me/userinfobot).

### 5. Run

```bash
python -m cos.main
```

Post a task-shaped message in the group ("we need to book Mia's dentist appointment") and CoS should capture it and ask who owns it.

### 6. Tests

```bash
pytest
```

Runs against a throwaway SQLite db — no Telegram or Anthropic credentials needed.

## Project layout

```
src/cos/
  config.py             # env + household.json loading
  db.py                 # SQLite schema (tasks)
  agent.py              # builds the Strands Agent, per chat_id
  prompts.py            # system prompt + household context
  response_tracker.py   # detects "ran a tool but never replied", triggers a retry
  main.py                # entry point
  tools/
    task_store.py        # create/update/query tasks, weekly metrics
    telegram_tools.py     # send_message, ask_choice
    calendar_tool.py      # Google Calendar wrapper (stub)
  telegram_bot/
    bot.py                # long-poll listener, callback routing, scheduled jobs
tests/
  test_task_store.py
  test_bot.py
  test_db.py
  test_response_tracker.py
```

## Next up

- Real Google Calendar wiring in `calendar_tool.py`.

Permanently out of scope for this MVP (see "Design deviations" above): private DM nudges, Google Sheets migration, weekly digest generator.
