"""Telegram listener + callback routing.

Built on python-telegram-bot's long-polling Application instead of the
community `strands-telegram-listener` package (see README "Design decisions
worth knowing"). Its only job is: get messages and button taps in front of
the agent, and get the agent's tool-driven replies out to Telegram. All
actual CoS behavior lives in the system prompt + tools, not here.

This is the "gateway" half of the architecture (see README "Architecture")
— it keeps this exact shape (long-polling + scheduling) whether the agent
invocation behind it (cos.brain.invoke_brain) runs in-process
(COS_AGENT_MODE=local) or against a deployed AgentCore Runtime endpoint
(COS_AGENT_MODE=agentcore).
"""

from __future__ import annotations

import logging
from datetime import time

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters

from cos.brain import invoke_brain, today_prefix
from cos.config import Settings

logger = logging.getLogger("cos.bot")


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or message.text is None or user is None:
        return

    sender_name = settings.household.name_for(user.id)
    instruction = (
        f"{today_prefix()} Telegram message from {sender_name} (user id {user.id}): "
        f'"{message.text}"'
    )
    await invoke_brain(settings, context.bot, instruction, log_context=f"handling message: {message.text!r}")


async def _handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()  # clear Telegram's loading spinner immediately

    task_id, _, option = query.data.partition("::")
    user = query.from_user
    sender_name = settings.household.name_for(user.id) if user else "someone"

    # Give instant visual feedback: swap the tapped keyboard out for a
    # confirmation line so the tap is visibly registered right away, rather
    # than leaving the buttons sitting there unchanged while the agent (which
    # can take a few seconds) works in the background before it can send its
    # own confirmation as a new message.
    if query.message is not None and query.message.text is not None:
        try:
            await query.edit_message_text(
                text=f"{query.message.text}\n\n☑️ {sender_name}: {option}",
                reply_markup=None,
            )
        except Exception:
            logger.exception("Failed to edit message after callback tap on task %s", task_id)

    instruction = (
        f"{today_prefix()} Button tap from {sender_name} (user id {user.id if user else 'unknown'}) "
        f'on task {task_id}: chose "{option}". Handle it (e.g. update ownership via '
        f"task_store) and confirm via send_message."
    )
    await invoke_brain(settings, context.bot, instruction, log_context=f"handling callback: {query.data!r}")


async def _handle_daily_nudge_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.job.data
    chat_id = settings.household.chat_id
    instruction = (
        f"{today_prefix()} Scheduled daily task check for chat_id {chat_id}. Call "
        "get_overdue_tasks and get_due_soon_tasks. For each task that hasn't been "
        "nudged today (check last_nudge_at), post a short nudge in this chat "
        "addressed to the owner by name — not a DM, this chat only — with a "
        "one-tap done option via ask_choice(options=[\"Done\"]), then "
        "update_task(last_nudge_at=now) for it. Don't nudge the same task twice "
        "in one day, and don't message about tasks that were already nudged today."
    )
    await invoke_brain(settings, context.bot, instruction, log_context="running daily nudge check")


async def _handle_weekly_metrics_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.job.data
    chat_id = settings.household.chat_id
    instruction = (
        f"{today_prefix()} Scheduled weekly stats check for chat_id {chat_id}. Run "
        "the WEEKLY STATS behavior now: call get_weekly_metrics and post the summary "
        "via send_message."
    )
    await invoke_brain(settings, context.bot, instruction, log_context="running weekly metrics check")


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
    if settings.persistence_backend == "sqlite":
        init_db(settings.db_path)

    app = build_application(settings)
    logger.info("CoS listening on chat_id=%s", settings.household.chat_id)
    app.run_polling(allowed_updates=Update.ALL_TYPES)
