"""Per-turn tracking of whether the agent actually replied to Telegram.

The system prompt is explicit that send_message/ask_choice are the agent's
*only* reply channel — a bare final text turn is never shown to anyone. In
practice, smaller/faster models (this project runs claude-haiku-4-5 for
cost) sometimes gather data via a read tool (e.g. get_open_tasks) and then
just write the answer as plain assistant text instead of calling
send_message, silently dropping the reply. This showed up live: an
on-demand shopping-list question got get_open_tasks called correctly, then
no send_message call followed, so nothing posted to the chat.

ResponseTracker hooks into Strands' AfterToolCallEvent (no changes needed to
the tool functions themselves) to record, for the current turn: whether any
tool ran at all, and whether one of the outbound-reply tools specifically
ran. bot.py uses this to detect "did real work but never replied" and retry
once with an explicit nudge — while leaving genuine silence (no tool calls
at all, e.g. idle chatter the agent correctly ignores) untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry

REPLY_TOOL_NAMES = {"send_message", "ask_choice"}


@dataclass
class ResponseTracker(HookProvider):
    any_tool_used: bool = field(default=False)
    responded: bool = field(default=False)

    def reset(self) -> None:
        self.any_tool_used = False
        self.responded = False

    @property
    def did_work_without_replying(self) -> bool:
        """True if the turn ran a tool (so it wasn't just silence-is-fine
        idle chatter) but never called send_message/ask_choice."""
        return self.any_tool_used and not self.responded

    def _on_after_tool_call(self, event: AfterToolCallEvent) -> None:
        self.any_tool_used = True
        if event.tool_use.get("name") in REPLY_TOOL_NAMES:
            self.responded = True

    def register_hooks(self, registry: HookRegistry, **kwargs: object) -> None:
        registry.add_callback(AfterToolCallEvent, self._on_after_tool_call)
