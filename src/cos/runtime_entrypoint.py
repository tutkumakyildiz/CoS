"""Amazon Bedrock AgentCore Runtime entrypoint — the deployable unit for the
hackathon target architecture (design spec §8's "brain").

This is intentionally the *only* file in the codebase that imports the
`bedrock_agentcore` SDK, so nothing else — the gateway, the tools, the test
suite — ever needs it installed or an AWS account to run. It's not used by
local/dev mode at all; see brain.py (the logic this wraps) and
telegram_bot/bot.py (the gateway, which calls brain.py directly in-process
today, and will call this deployed endpoint instead once it's live).

Install the extra before deploying:
    pip install -e ".[agentcore]"
(package name/version not yet verified against a real deploy — confirm
against AWS's current docs at deploy time, per design spec §8's own note
that this tooling moves fast.)

Deploy with the AgentCore CLI/toolkit current at deploy time — not run here.
"""

from __future__ import annotations

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # type: ignore[import-not-found]
from telegram import Bot

from cos.brain import handle_payload
from cos.config import Settings, load_settings
from cos.db import init_db

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
