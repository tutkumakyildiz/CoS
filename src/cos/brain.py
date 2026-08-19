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

import logging
from datetime import date
from typing import Any

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


async def handle_payload(payload: dict[str, Any], settings: Settings, bot: Bot) -> dict[str, Any]:
    """The AgentCore-entrypoint shape: one JSON-able dict in, one JSON-able
    dict out. `payload` carries the same two things bot.py's handlers already
    build today (`instruction`, `log_context`) — see runtime_entrypoint.py.
    """
    instruction = payload["instruction"]
    log_context = payload.get("log_context", "handling AgentCore invocation")
    await run_instruction(settings, bot, instruction, log_context=log_context)
    return {"status": "ok"}
