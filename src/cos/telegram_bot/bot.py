"""Telegram listener + callback routing — spec §4.4/§4.5 and §6 "Capture flow".

Built on python-telegram-bot's long-polling Application instead of the
community `strands-telegram-listener` package (see README "Design
deviations"). Its only job is: get messages and button taps in front of the
agent, and get the agent's tool-driven replies out to Telegram. All actual
CoS behavior lives in the system prompt + tools, not here.
"""

from __future__ import annotations

import logging
from datetime import date, time

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from cos.agent import get_agent, get_response_tracker
from cos.config import Settings

logger = logging.getLogger("cos.bot")

# Smaller/faster models (this project runs claude-haiku-4-5 for cost) sometimes
# gather data via a read tool and then just write the answer as plain assistant
# text instead of calling send_message/ask_choice — silently dropping the
# reply, since those tools are the agent's only channel out. Seen live: an
# on-demand shopping-list question fetched the task list correctly but never
# posted anything. _invoke_agent detects that pattern (a tool ran, but neither
# reply tool did) via ResponseTracker and retries once with this nudge.
_RETRY_NUDGE = (
    "You ran a tool for the previous message but never replied via send_message "
    "or ask_choice, so nothing was actually sent — the person is still waiting. "
    "Reply now with what you found."
)


def _today_prefix() -> str:
    # The model has no innate sense of "now" — without this, relative dates
    # ("before September", "next Friday") get resolved against its training
    # data instead of the real calendar and can land a year or more off.
    return f"[Today's date is {date.today().isoformat()}]"


async def _invoke_agent(settings: Settings, bot, instruction: str, *, log_context: str) -> None:
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
            await agent.invoke_async(_RETRY_NUDGE)
        except Exception:
            logger.exception("Agent failed on retry after %s", log_context)


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or message.text is None or user is None:
        return

    sender_name = settings.household.name_for(user.id)
    instruction = (
        f"{_today_prefix()} Telegram message from {sender_name} (user id {user.id}): "
        f'"{message.text}"'
    )
    await _invoke_agent(settings, context.bot, instruction, log_context=f"handling message: {message.text!r}")


async def _handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()  # clear Telegram's loading spinner immediately

    task_id, _, option = query.data.partition("::")
    user = query.from_user
    sender_name = settings.household.name_for(user.id) if user else "someone"
    instruction = (
        f"{_today_prefix()} Button tap from {sender_name} (user id {user.id if user else 'unknown'}) "
        f'on task {task_id}: chose "{option}". Handle it (e.g. update ownership via '
        f"task_store) and confirm via send_message."
    )
    await _invoke_agent(settings, context.bot, instruction, log_context=f"handling callback: {query.data!r}")


async def _handle_daily_nudge_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.job.data
    chat_id = settings.household.chat_id
    instruction = (
        f"{_today_prefix()} Scheduled daily task check for chat_id {chat_id}. Call "
        "get_overdue_tasks and get_due_soon_tasks. For each task that hasn't been "
        "nudged today (check last_nudge_at), post a short nudge in this chat "
        "addressed to the owner by name — not a DM, this chat only — with a "
        "one-tap done option via ask_choice(options=[\"Done\"]), then "
        "update_task(last_nudge_at=now) for it. Don't nudge the same task twice "
        "in one day, and don't message about tasks that were already nudged today."
    )
    await _invoke_agent(settings, context.bot, instruction, log_context="running daily nudge check")


async def _handle_weekly_metrics_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.job.data
    chat_id = settings.household.chat_id
    instruction = (
        f"{_today_prefix()} Scheduled weekly stats check for chat_id {chat_id}. Run "
        "the WEEKLY STATS behavior now: call get_weekly_metrics and post the summary "
        "via send_message."
    )
    await _invoke_agent(settings, context.bot, instruction, log_context="running weekly metrics check")


def build_application(settings: Settings) -> Application:
    chat_id = int(settings.household.chat_id)

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Chat(chat_id=chat_id),
            lambda update, context: _handle_message(update, context, settings),
        )
    )
    app.add_handler(CallbackQueryHandler(lambda update, context: _handle_callback(update, context, settings)))

    if app.job_queue is None:
        raise RuntimeError(
            "JobQueue not available — install the job-queue extra: "
            'pip install "python-telegram-bot[job-queue]"'
        )
    app.job_queue.run_daily(
        _handle_daily_nudge_check,
        time=time(hour=settings.nudge_hour, tzinfo=settings.nudge_timezone),
        name="daily_nudge_check",
        chat_id=chat_id,
        data=settings,
    )
    app.job_queue.run_daily(
        _handle_weekly_metrics_check,
        time=time(hour=settings.metrics_hour, minute=settings.metrics_minute, tzinfo=settings.nudge_timezone),
        days=(settings.metrics_weekday,),
        name="weekly_metrics_check",
        chat_id=chat_id,
        data=settings,
    )

    return app


def run() -> None:
    from cos.config import load_settings
    from cos.db import init_db

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    settings = load_settings()
    init_db(settings.db_path)

    app = build_application(settings)
    logger.info("CoS listening on chat_id=%s", settings.household.chat_id)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
