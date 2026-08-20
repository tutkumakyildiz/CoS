"""Outbound Telegram actions the agent can take.

Built directly on python-telegram-bot rather than the community
`strands-telegram` package (see README "Design decisions worth knowing").
Bound to a single bot + chat_id at construction time, same reasoning as
task_store: the agent should never need to (and never be able to) target a
chat_id other than the one it's running for.

Two tools, matching the two shapes of outbound message the system prompt
actually needs:
- send_message: plain text (confirmations, nudges, query replies)
- ask_choice: text + inline keyboard buttons (ownership decisions), where each
  tapped button routes back into the agent via the bot's callback handler
  (see telegram_bot/bot.py)
"""

from __future__ import annotations

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from strands import tool


def build_telegram_tools(bot: Bot, chat_id: str) -> list:
    @tool
    async def send_message(text: str) -> str:
        """Send a plain text message to the household chat.

        Args:
            text: Message text. Keep it to 1-3 short lines — this is Telegram, not email.
        """
        await bot.send_message(chat_id=chat_id, text=text)
        return "sent"

    @tool
    async def ask_choice(text: str, task_id: str, options: list[str]) -> str:
        """Send a message with inline-keyboard buttons for the user to tap, tied to a task.

        Use this for ownership decisions and similar clear-choice questions, e.g.
        options=["Assign to <partner 1's real name>", "Assign to <partner 2's real name>",
        "Split - let's talk"] — one option per partner, substituting each partner's actual
        name from the system prompt's household roster (never a placeholder or example
        name, and no separate "I'll take it" option — the sender claims a task by tapping
        their own name). Prefer this over asking the user to type a free-text reply when
        the response is a clear choice. A tapped button will come back to you as a
        follow-up instruction naming the task_id, the option chosen, and who tapped it.

        Args:
            text: The question to ask, 1-2 short lines.
            task_id: The task this choice is about, so the tap can be routed back correctly.
            options: 2-3 short button labels.
        """
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton(opt, callback_data=f"{task_id}::{opt}")] for opt in options]
        )
        await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        return "sent"

    return [send_message, ask_choice]
