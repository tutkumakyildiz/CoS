# CoS

Household chief-of-staff Telegram bot, built on the [Strands Agents SDK](https://strandsagents.com/). It lives in a shared household group chat, turns loose mentions ("we need to book Mia's dentist appointment") into tracked tasks, asks who's taking each one, follows up so nothing falls through the cracks, and gives a neutral weekly picture of who's carrying what.

## Architecture

![CoS agent-invocation path: default vs. fallback](docs/architecture.svg)

CoS splits into a **gateway** and a **brain**, because Amazon Bedrock AgentCore Runtime is a synchronous request/response HTTP service with no native support for a long-polling Telegram listener or scheduled background jobs:

- **Gateway** (`telegram_bot/bot.py`) — a normal long-running process: the Telegram long-poll listener, plus the daily-nudge and weekly-metrics `JobQueue` schedulers. Unchanged regardless of which brain path is active.
- **Brain** (`brain.py` / `agent.py`) — the actual Strands Agent and its tool-calling loop. By default it's invoked as a deployed **Bedrock AgentCore Runtime** endpoint (a container built from the root `Dockerfile`, running `runtime_entrypoint.py`, invoked per message via `invoke_agent_runtime`), backed by **Amazon Bedrock** (Claude) and **DynamoDB** (`cos_tasks` table). A local, in-process fallback path (direct Anthropic API + SQLite, no AgentCore round-trip) stays available behind config flags — see "Model provider" and "Gateway/brain mode" below.

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

Runs on **Amazon Bedrock** (Claude via `strands.models.bedrock.BedrockModel`, EU cross-region inference profile in `eu-central-1`), **DynamoDB** (`cos_tasks` table, `PAY_PER_REQUEST`), and **Bedrock AgentCore Runtime** (the "brain" — `runtime_entrypoint.py`, deployed as a container, invoked per-message via `invoke_agent_runtime`) — see "Model provider" and "Gateway/brain mode" below. The direct-Anthropic-API, SQLite, and in-process-agent paths are all kept as fallbacks (`COS_MODEL_PROVIDER=anthropic`, `COS_PERSISTENCE_BACKEND=sqlite`, `COS_AGENT_MODE=local`). Real household task data was migrated from the original SQLite file into DynamoDB, not started fresh. Live-verified end-to-end through the deployed AgentCore Runtime: an inbound message, a button-tap callback, and a scheduled daily-nudge job all worked, including the reply-reliability safety net.

**Not yet built:** nothing outstanding on the technical side — see "Next up" below for what's next in scope.

## Model provider

Set `COS_MODEL_PROVIDER` in `.env`:
- `bedrock` (current default in this repo's own `.env`) — Amazon Bedrock. Needs `COS_AWS_REGION` and a Bedrock-shaped `COS_MODEL_ID` (an inference profile id in regions like `eu-central-1`, e.g. `eu.anthropic.claude-haiku-4-5-20251001-v1:0` — find yours with `aws bedrock list-inference-profiles --region <region>`). Optional `COS_AWS_PROFILE` for a named local AWS CLI profile.
- `anthropic` — direct Anthropic API (fallback path). Needs `ANTHROPIC_API_KEY` and a bare model name in `COS_MODEL_ID` (e.g. `claude-haiku-4-5`).

## Gateway/brain mode

Set `COS_AGENT_MODE` in `.env`:
- `local` — the Telegram gateway (`bot.py`) runs the Strands Agent in-process, no AgentCore round-trip.
- `agentcore` (current default in this repo's own `.env`) — the gateway instead fires each instruction at a deployed Bedrock AgentCore Runtime endpoint (`COS_AGENTCORE_RUNTIME_ARN`, required in this mode) via `invoke_agent_runtime`. The deployed container (built from the root `Dockerfile`, running `runtime_entrypoint.py`) sends the Telegram reply itself, as a side effect — the local gateway process never touches the model or the reply in this mode.

Deploying/updating the container: build for `linux/arm64` (`docker buildx build --platform linux/arm64 -t cos-agentcore-brain .`), push to the ECR repo, then call `bedrock-agentcore-control`'s `update-agent-runtime` (or `create-agent-runtime` for a first deploy) with the new image URI. Note: AgentCore pins existing sessions to their already-warm container instance — an in-flight `runtimeSessionId` may keep hitting the pre-update container until it recycles, so a fresh session (or waiting it out) is needed to exercise a just-deployed change.

See `.env.example` for the full set of variables.

## Design decisions worth knowing

Places the implementation deliberately diverges from the "obvious" approach:

| Instead of | CoS does | Why |
|---|---|---|
| Community `strands-telegram` / `strands-telegram-listener` packages | `python-telegram-bot`, wrapped in custom Strands tools | Those community packages are unreviewed/unmaintained-risk. |
| Google Sheets persistence | SQLite (local) / DynamoDB (deployed) | Kept permanently by design choice — no GCP dependency. |
| Private DM nudges | Nudges posted in the shared group chat, addressed to the owner by name | Avoids requiring each partner to `/start` the bot privately before it can message them. |
| A weekly digest with an imbalance callout | A neutral weekly stats summary, no praise/blame | Narrower, purpose-built replacement — partners can still ask about open tasks any time via on-demand queries. |
| Google Calendar integration | Permanent no-op stub (`calendar_tool.py` always reports "not connected") | Kept permanently by design choice — not planned. |

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
  config.py                       # env + household.json loading
  db.py                           # SQLite connection/schema setup
  agent.py                        # builds the Strands Agent, per chat_id
  brain.py                        # agent-invocation dispatch: local in-process vs. AgentCore Runtime
  runtime_entrypoint.py           # BedrockAgentCoreApp adapter — the deployed container's entrypoint
  prompts.py                      # system prompt + household context
  response_tracker.py             # detects "ran a tool but never replied", triggers a retry
  main.py                         # entry point
  persistence/
    base.py                       # TaskStoreBackend interface
    sqlite_backend.py             # local dev backend
    dynamodb_backend.py           # deployed backend
  tools/
    task_store.py                 # create/update/query tasks, weekly metrics
    telegram_tools.py             # send_message, ask_choice
    calendar_tool.py              # permanent no-op stub — see "Design decisions"
  telegram_bot/
    bot.py                        # long-poll listener, callback routing, scheduled jobs
tests/
  test_task_store.py
  test_bot.py
  test_brain.py
  test_db.py
  test_persistence_dynamodb.py
  test_response_tracker.py
deploy/iam/                       # reference IAM policy templates for the AgentCore execution role
docs/
  architecture.svg                # diagram referenced above
```

## Next up

Broader household support past two partners, and DM-based nudges as an opt-in alongside the group-chat nudges CoS uses today.

Permanently out of scope for this MVP (see "Design decisions worth knowing" above): Google Sheets persistence, a blame-y weekly digest, and real Google Calendar integration (`calendar_tool.py` stays a permanent no-op stub by design).
