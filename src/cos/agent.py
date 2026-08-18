"""Builds the single Strands Agent — spec §2 ("Why single-agent for MVP").

One long-lived Agent instance per chat_id, reused across messages so the
conversation_manager keeps recent context (e.g. a button tap referring back
to a task mentioned a few messages ago). MVP is one household/one chat, but
this is already chat_id-keyed since the data model is (spec §3: "multi-
household ready later").
"""

from __future__ import annotations

from telegram import Bot

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.anthropic import AnthropicModel

from cos.config import Settings
from cos.prompts import build_system_prompt
from cos.tools.calendar_tool import build_calendar_tools
from cos.tools.task_store import build_task_store_tools
from cos.tools.telegram_tools import build_telegram_tools

_agents: dict[str, Agent] = {}


def get_agent(settings: Settings, bot: Bot) -> Agent:
    """Get (or lazily build) the agent for this process's one configured chat."""
    chat_id = settings.household.chat_id
    if chat_id in _agents:
        return _agents[chat_id]

    model = AnthropicModel(
        client_args={"api_key": settings.anthropic_api_key},
        model_id=settings.model_id,
        max_tokens=1024,
    )

    tools = [
        *build_task_store_tools(chat_id),
        *build_telegram_tools(bot, chat_id),
        *build_calendar_tools(),
    ]

    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=build_system_prompt(chat_id, settings.household.partners),
        conversation_manager=SlidingWindowConversationManager(window_size=40),
    )
    _agents[chat_id] = agent
    return agent
