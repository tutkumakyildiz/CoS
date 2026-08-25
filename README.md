# CoS — Chief of Staff for Your Household

**Track:** Everyday Agents

## What it does

CoS is a Telegram bot that lives inside your household group chat and quietly manages the mental load of running a home — the invisible layer of remembering, assigning, and tracking chores, errands, and to-dos that usually falls disproportionately on one partner.

Instead of a chore app nobody opens, CoS listens to the conversation you're already having. Mention something that needs doing — "we're out of milk," "someone needs to book the dentist" — and CoS captures it as a structured task automatically, no data entry required.

From there, CoS handles the full lifecycle of a task:

- **Delegation** — it asks who's taking ownership via inline buttons, or offers a "Split — let's talk" option when a task needs a real conversation instead of a snap assignment.
- **Completion** — tasks close naturally, either by tapping "Done" on a reminder or just saying so in chat ("I bought milk").
- **Daily nudges** — owners get reminded of what's due soon, posted publicly in the group and addressed to them by name, so accountability stays visible to everyone, not just the person nagging.
- **On-demand queries** — anyone can ask CoS what's open right now ("what should I get from the market") and get a live answer.
- **Weekly stats** — a neutral, factual summary of tasks captured and completed per partner, and how many were resolved without needing a reminder at all. No praise, no blame — just visibility.

## Who it's for

Couples and households who split responsibilities but keep running into the same argument: one person is doing all the remembering, even when chores are technically "shared." CoS is for any household — partners, roommates, or families — that wants task ownership to be explicit and measurable instead of assumed.

## Why it matters

Research on household labor consistently points to the mental load — the invisible work of noticing, planning, and tracking — as one of the most persistent drivers of inequity at home, separate from who does the physical task. CoS doesn't just split chores; it makes the invisible visible, turning "I told you to remember this" into a transparent, shared system that lives where the household already talks.

## How it works

CoS runs as an autonomous background agent built on the Strands Agents SDK and deployed on Amazon Bedrock AgentCore. It monitors the group chat continuously, uses natural-language understanding to detect actionable mentions, converts them into structured task objects, manages ownership state and reminder scheduling, and only surfaces to the group when a decision or nudge is actually needed — never as another app to check.

## Architecture

![CoS architecture](docs/architecture.svg)

CoS splits into a **gateway** and a **brain**, because Amazon Bedrock AgentCore Runtime is a synchronous request/response HTTP service with no native support for a long-polling Telegram listener or scheduled background jobs:

- **Gateway** (`telegram_bot/bot.py`) — a normal long-running process: the Telegram long-poll listener, plus the daily-nudge and weekly-metrics `JobQueue` schedulers. Unchanged regardless of which brain path is active. Runs as an always-on **ECS Fargate** task in production — see "Deploying the gateway" below.
- **Brain** (`brain.py` / `agent.py`) — the actual Strands Agent and its tool-calling loop. By default it's invoked as a deployed **Bedrock AgentCore Runtime** endpoint (a container built from the root `Dockerfile`, running `runtime_entrypoint.py`, invoked per message via `invoke_agent_runtime`), backed by **Amazon Bedrock** (Claude) and **DynamoDB** (`cos_tasks` table). A local, in-process fallback path (direct Anthropic API + SQLite, no AgentCore round-trip) stays available behind config flags — see "Model provider" and "Gateway/brain mode" below.
- **Web dashboard** (`webapp/`) — an optional, separate read-only view: a task list and a gateway status/restart panel, behind a shared-password login. Runs on **AWS App Runner**. See "Web dashboard" below.

## Features

- **Capture** — turns natural mentions in the group chat into structured tasks.
- **Delegation** — asks who owns a new task via inline buttons (or "Split — let's talk").
- **Completion** — close a task either by tapping "Done" on a nudge, or just saying so in chat ("I bought milk").
- **Daily nudges** — reminds owners of tasks due soon, posted in the group and addressed to them by name.
- **On-demand queries** — ask CoS what's open any time ("what should I get from the market").
- **Weekly stats** — a neutral summary of tasks captured/completed per partner, and how many were resolved without a reminder. No praise, no blame.
- **Reply safety net** — the agent retries automatically if it silently forgets to send its reply.
- **Web search** — answers things not in the task list (store hours, "find a plumber near us") via Tavily. Optional; see "Optional: web search + Google Calendar" below.
- **Google Calendar** — cross-references seasonal/recurring tasks against real calendar events, and can put a task with a due date onto the calendar. Optional; same section below.

## Status

Core MVP is built and live-tested end-to-end in a real household group: capture, delegation, both completion paths, daily nudges, weekly stats, and the reply safety net all work in production use today.

Runs on **Amazon Bedrock** (Claude via `strands.models.bedrock.BedrockModel`, EU cross-region inference profile in `eu-central-1`), **DynamoDB** (`cos_tasks` table, `PAY_PER_REQUEST`), and **Bedrock AgentCore Runtime** (the "brain" — `runtime_entrypoint.py`, deployed as a container, invoked per-message via `invoke_agent_runtime`) — see "Model provider" and "Gateway/brain mode" below. The direct-Anthropic-API, SQLite, and in-process-agent paths are all kept as fallbacks (`COS_MODEL_PROVIDER=anthropic`, `COS_PERSISTENCE_BACKEND=sqlite`, `COS_AGENT_MODE=local`). Real household task data was migrated from the original SQLite file into DynamoDB, not started fresh. Live-verified end-to-end through the deployed AgentCore Runtime: an inbound message, a button-tap callback, and a scheduled daily-nudge job all worked, including the reply-reliability safety net.

The **gateway** now runs live on **ECS Fargate** (`cos-cluster`/`cos-gateway`, `eu-central-1`) instead of a local process — cutover completed and live-verified: clean startup with no Telegram polling conflicts, a real inbound message and a real button-tap callback both round-tripped correctly through the deployed AgentCore brain and back to Telegram. `TELEGRAM_BOT_TOKEN` now lives in Secrets Manager rather than a plaintext deploy file.

The **web dashboard** is fully built and unit-tested (`src/cos/webapp`, both Docker images pushed to ECR, the `cos-webapp-instance-role` IAM role created) and confirmed working end-to-end when run locally against the real production data (real tasks, real gateway status), but **not yet deployed anywhere reachable over the internet** — paused with the hosting approach still undecided. App Runner is blocked account-wide (`SubscriptionRequiredException`, not an IAM issue); an ECS Fargate + ALB fallback got as far as an `iam:CreateServiceLinkedRole` block on this account's first-ever ALB. See `deploy/webapp/README.md`'s "Status" section for exact state and options before resuming.

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

## Deploying the gateway (ECS Fargate)

The gateway is a blocking Telegram long-poll process with two `JobQueue` scheduled jobs — it needs to stay running 24/7, but (unlike the brain) is not a request/response HTTP service, so it doesn't fit AgentCore Runtime. It runs instead as an always-on **ECS Fargate** task: no load balancer (it takes no inbound traffic at all — pure outbound long-poll + outbound `invoke_agent_runtime` calls), `TELEGRAM_BOT_TOKEN` resolved from **AWS Secrets Manager**, and a deployment config (`minimumHealthyPercent: 0, maximumPercent: 100`) that guarantees the old task fully stops before a new one starts — this matters because two long-pollers sharing one bot token causes Telegram's `getUpdates` to 409 (`Conflict: terminated by other getUpdates request`).

Full setup, cutover sequence (how to move from a local `python -m cos.main` process to the ECS-hosted one without hitting that conflict), and redeploy commands: see [`deploy/gateway/README.md`](deploy/gateway/README.md).

## Web dashboard

An optional read-only dashboard (`src/cos/webapp`, install with `pip install -e ".[webapp]"`): a task list (open + done, filterable by status/owner, partner display names resolved via `household.json`) and a bot status/restart panel (checks the gateway's ECS service health, can trigger a redeploy). Server-rendered FastAPI + Jinja2, no SPA framework — this is a basic internal tool, not a task-editing UI (task changes still only happen via Telegram, matching CoS's actual design point). Gated behind a single shared password (`COS_WEBAPP_PASSWORD`) and a signed session cookie (`COS_WEBAPP_SESSION_SECRET`) — no per-user accounts.

Run locally: `python -m cos.webapp` (reads the same `.env`/`household.json` as the bot, plus the two `COS_WEBAPP_*` vars — see `.env.example`). Deploys on **AWS App Runner** — image built and pushed, IAM role created, but the App Runner service itself isn't up yet (blocked on account activation, see "Status" above) — see [`deploy/webapp/README.md`](deploy/webapp/README.md).

## Setup

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

(Add `,webapp` to that extras list — `pip install -e ".[dev,webapp]"` — if you also want to run the web dashboard locally; see "Web dashboard" below.)

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

### 7. Optional: web search + Google Calendar

Both degrade gracefully to "not connected" if skipped — the bot works fine without either.

**Web search** (Tavily): sign up at https://app.tavily.com, copy an API key into `.env` as `TAVILY_API_KEY`. No extra install — already covered by the base `strands-agents-tools` dependency.

**Google Calendar** — writes to one partner's primary calendar (OAuth-consent as that person, not a separately shared calendar):

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. **APIs & Services → OAuth consent screen**: user type **External**, publishing status **Testing** (fine for personal Gmail + 1-2 test users — avoids Google's verification review), add the chosen partner's Gmail as a test user.
3. **APIs & Services → Library**: enable the **Google Calendar API**.
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**, type **Desktop app**. Note the client id/secret.
5. Install the extra and run the one-time authorization script:
   ```bash
   pip install -e ".[dev,calendar]"
   GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python scripts/authorize_google_calendar.py
   ```
   This opens a browser for you to sign in as the chosen partner and grant calendar access, then prints a refresh token.
6. Add all three (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`) to `.env`.

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
  telegram_bot/
    bot.py                        # long-poll listener, callback routing, scheduled jobs
  webapp/                         # optional read-only dashboard (see "Web dashboard" above)
    app.py                        # FastAPI app factory
    auth.py                       # shared-password login + session gate
    tasks_view.py                 # GET /tasks — task list
    bot_status.py                 # GET /status, POST /status/restart — gateway ECS health/restart
tests/
  test_task_store.py
  test_bot.py
  test_brain.py
  test_db.py
  test_persistence_dynamodb.py
  test_persistence_sqlite.py
  test_response_tracker.py
  test_webapp_tasks.py
  test_webapp_status.py
deploy/
  iam/                            # reference IAM policy templates (AgentCore, gateway, webapp roles)
  gateway/                        # gateway Dockerfile + ECS task-def/service templates + deploy guide
  webapp/                         # webapp Dockerfile + App Runner deploy guide
docs/
  architecture.svg                # diagram referenced above
```

## Next up

Multi-tenant support (multiple households/bots sharing one deployment, with a self-service onboarding flow) is a planned future direction — the persistence layer is already `chat_id`-scoped and ready for it; the gateway/brain process model is intentionally kept single-household for now.
