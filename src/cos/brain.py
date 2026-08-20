"""The agent-invocation "brain" — split out from the Telegram gateway
(telegram_bot/bot.py) per the hackathon target architecture (design spec
§8). The gateway stays a normal long-running process (Telegram polling +
scheduling); everything here is what eventually runs inside Amazon Bedrock
AgentCore Runtime instead, invoked per-message via boto3's
invoke_agent_runtime rather than as a local function call.

Today (no AgentCore deployment yet — see README "Design deviations"),
`run_instruction` is still called in-process by bot.py, so nothing about the
gateway's actual behavior has changed; this file is the extraction, not the
deployment. `handle_payload` is the JSON-in/JSON-out shape an AgentCore
`@app.entrypoint` needs — see runtime_entrypoint.py, the separate adapter
that wraps this for real deployment (kept separate so the AgentCore SDK
dependency never has to be installed for local dev or the test suite).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from typing import Any

import boto3
from telegram import Bot

from cos.agent import get_agent, get_response_tracker
from cos.config import Settings

logger = logging.getLogger("cos.brain")

# Smaller/faster models (this project runs claude-haiku-4-5 for cost) sometimes
# gather data via a read tool and then just write the answer as plain assistant
# text instead of calling send_message/ask_choice — silently dropping the
# reply, since those tools are the agent's only channel out. Seen live: an
# on-demand shopping-list question fetched the task list correctly but never
# posted anything. run_instruction detects that pattern (a tool ran, but
# neither reply tool did) via ResponseTracker and retries once with this nudge.
RETRY_NUDGE = (
    "You ran a tool for the previous message but never replied via send_message "
    "or ask_choice, so nothing was actually sent — the person is still waiting. "
    "Reply now with what you found."
)


def today_prefix() -> str:
    # The model has no innate sense of "now" — without this, relative dates
    # ("before September", "next Friday") get resolved against its training
    # data instead of the real calendar and can land a year or more off.
    return f"[Today's date is {date.today().isoformat()}]"


async def run_instruction(settings: Settings, bot: Bot, instruction: str, *, log_context: str) -> None:
    """Run one turn of the agent for `settings.household.chat_id`, with the
    silent-drop safety net (see module docstring + response_tracker.py).
    Replies happen as a side effect via the agent's send_message/ask_choice
    tools — this returns nothing, same as before the brain/gateway split.
    """
    agent = get_agent(settings, bot)
    tracker = get_response_tracker(settings)
    tracker.reset()
    try:
        await agent.invoke_async(instruction)
    except Exception:
        logger.exception("Agent failed %s", log_context)
        return

    if tracker.did_work_without_replying:
        logger.warning(
            "Agent ran a tool but never called send_message/ask_choice while %s — retrying once",
            log_context,
        )
        tracker.reset()
        try:
            await agent.invoke_async(RETRY_NUDGE)
        except Exception:
            logger.exception("Agent failed on retry after %s", log_context)


async def invoke_remote(settings: Settings, instruction: str, *, log_context: str) -> None:
    """Gateway-side call to a deployed Bedrock AgentCore Runtime endpoint
    (design spec §8, hackathon Phase C), used instead of `run_instruction`
    when `settings.agent_mode == "agentcore"`. Fires the same instruction at
    the deployed container via `invoke_agent_runtime`; the container runs
    this exact module's `run_instruction` internally (via runtime_entrypoint.py
    -> handle_payload) and sends the Telegram reply itself as a side effect —
    this function doesn't touch `bot` at all, deliberately, and just waits for
    the call to complete.

    `runtimeSessionId` is pinned per chat_id so repeat invocations route back
    to the same warm container/session where possible, the closest AgentCore
    equivalent to `agent.py`'s in-process per-chat_id Agent cache.
    """
    client = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region).client(
        "bedrock-agentcore"
    )
    session_id = f"cos-chat-{settings.household.chat_id}".ljust(33, "0")
    body = json.dumps({"instruction": instruction, "log_context": log_context}).encode("utf-8")

    def _invoke() -> None:
        resp = client.invoke_agent_runtime(
            agentRuntimeArn=settings.agentcore_runtime_arn,
            runtimeSessionId=session_id,
            payload=body,
        )
        resp["response"].read()  # drain the stream; body is just {"status": "ok"}

    try:
        await asyncio.to_thread(_invoke)
    except Exception:
        logger.exception("AgentCore Runtime invocation failed %s", log_context)


async def invoke_brain(settings: Settings, bot: Bot, instruction: str, *, log_context: str) -> None:
    """Gateway's single dispatch point: local in-process agent, or the
    deployed AgentCore Runtime, chosen by `settings.agent_mode`. All four
    of bot.py's handlers (message, callback, daily nudge, weekly metrics)
    call this instead of `run_instruction` directly.
    """
    if settings.agent_mode == "agentcore":
        await invoke_remote(settings, instruction, log_context=log_context)
    else:
        await run_instruction(settings, bot, instruction, log_context=log_context)


async def handle_payload(payload: dict[str, Any], settings: Settings, bot: Bot) -> dict[str, Any]:
    """The AgentCore-entrypoint shape: one JSON-able dict in, one JSON-able
    dict out. `payload` carries the same two things bot.py's handlers already
    build today (`instruction`, `log_context`) — see runtime_entrypoint.py.
    """
    instruction = payload["instruction"]
    log_context = payload.get("log_context", "handling AgentCore invocation")
    await run_instruction(settings, bot, instruction, log_context=log_context)
    return {"status": "ok"}
