"""Amazon Bedrock AgentCore Runtime entrypoint — the deployable unit for the
"brain" half of the architecture (see README "Architecture").

This is intentionally the *only* file in the codebase that imports the
`bedrock_agentcore` SDK, so nothing else — the gateway, the tools, the test
suite — ever needs it installed or an AWS account to run. It's not used by
local/dev mode at all; see brain.py (the logic this wraps) and
telegram_bot/bot.py (the gateway, which calls brain.py directly in-process
today, and will call this deployed endpoint instead once it's live).

Install the extra before deploying:
    pip install -e ".[agentcore]"
(verified against a real deploy — see README "Status" — but this tooling
moves fast, so double-check package name/version against AWS's current docs
if it's been a while.)

Deploy with the AgentCore CLI/toolkit current at deploy time — not run here.
"""

from __future__ import annotations

import logging

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # type: ignore[import-not-found]
from telegram import Bot

from cos.brain import handle_payload
from cos.config import Settings, load_settings
from cos.db import init_db

# Without this, cos.brain's logger (and everything else under the root
# logger) has no handler inside the container — logger.exception() calls
# (e.g. run_instruction's silent-drop-retry warning, or any unhandled
# exception it catches and logs) go nowhere, not even CloudWatch. bot.py's
# run() sets this up the same way for local/dev mode; this is the AgentCore
# equivalent. Found the hard way: a failed invocation showed only AgentCore's
# own "completed successfully" line in CloudWatch, no app-level detail at all.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = BedrockAgentCoreApp()

_settings: Settings | None = None
_bot: Bot | None = None


def _get_context() -> tuple[Settings, Bot]:
    """Lazy, cached per-container init — same reasoning as agent.py's
    _agents cache: build once, reuse across invocations of the same
    container instance."""
    global _settings, _bot
    if _settings is None:
        _settings = load_settings()
        init_db(_settings.db_path)
        _bot = Bot(token=_settings.telegram_bot_token)
    assert _bot is not None
    return _settings, _bot


@app.entrypoint
async def invoke(payload: dict) -> dict:
    settings, bot = _get_context()
    return await handle_payload(payload, settings, bot)


if __name__ == "__main__":
    app.run()
