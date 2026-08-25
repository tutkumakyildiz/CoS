"""Builds the single Strands Agent.

One agent handles everything — capture, delegation, follow-up, weekly
stats — through a small, well-scoped toolset and a single system prompt,
rather than splitting into multiple specialized agents. Simpler to reason
about and debug, and sufficient for a single-household MVP.

One long-lived Agent instance per chat_id, reused across messages so the
conversation_manager keeps recent context (e.g. a button tap referring back
to a task mentioned a few messages ago). Only one household/chat is in use
today, but keying by chat_id from the start keeps multi-household support a
config change away rather than a rearchitecture.
"""

from __future__ import annotations

import boto3
from telegram import Bot

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.anthropic import AnthropicModel
from strands.models.bedrock import BedrockModel

from cos.config import Settings
from cos.persistence import get_backend
from cos.prompts import build_system_prompt
from cos.response_tracker import ResponseTracker
from cos.tools.amazon_tool import build_amazon_tools
from cos.tools.calendar_tool import build_calendar_tools
from cos.tools.search_tool import build_search_tools
from cos.tools.task_store import build_task_store_tools
from cos.tools.telegram_tools import build_telegram_tools

_agents: dict[str, Agent] = {}
_trackers: dict[str, ResponseTracker] = {}


def _build_model(settings: Settings) -> AnthropicModel | BedrockModel:
    """Model provider swap point — see README "Model provider".

    "anthropic" calls the Anthropic API directly. "bedrock" routes the same
    Agent through Amazon Bedrock instead — note COS_MODEL_ID needs a
    Bedrock-shaped id for that provider (e.g. an EU
    cross-region inference profile like
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0"), not the bare Anthropic
    model name used by the "anthropic" provider.
    """
    if settings.model_provider == "bedrock":
        session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        return BedrockModel(
            boto_session=session,
            model_id=settings.model_id,
            max_tokens=1024,
        )
    return AnthropicModel(
        client_args={"api_key": settings.anthropic_api_key},
        model_id=settings.model_id,
        max_tokens=1024,
    )


def get_agent(settings: Settings, bot: Bot) -> Agent:
    """Get (or lazily build) the agent for this process's one configured chat."""
    chat_id = settings.household.chat_id
    if chat_id in _agents:
        return _agents[chat_id]

    model = _build_model(settings)

    tools = [
        *build_task_store_tools(chat_id, get_backend(settings)),
        *build_telegram_tools(bot, chat_id),
        *build_calendar_tools(settings),
        *build_search_tools(settings),
        *build_amazon_tools(settings),
    ]

    tracker = ResponseTracker()
    agent = Agent(
        model=model,
        tools=tools,
        system_prompt=build_system_prompt(chat_id, settings.household.partners),
        conversation_manager=SlidingWindowConversationManager(window_size=40),
        hooks=[tracker],
    )
    _agents[chat_id] = agent
    _trackers[chat_id] = tracker
    return agent


def get_response_tracker(settings: Settings) -> ResponseTracker:
    """The ResponseTracker for this chat's agent — call get_agent(settings, bot)
    at least once first so it's been created."""
    return _trackers[settings.household.chat_id]
