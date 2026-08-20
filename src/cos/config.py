"""Environment + household configuration loading.

Per the design spec §8: "Telegram user_id -> owner mapping should be a simple
config value per chat, not a full user system." That's `household.json`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class HouseholdConfig:
    chat_id: str
    partners: dict[str, str]  # telegram_user_id (str) -> display name

    def name_for(self, user_id: str | int) -> str:
        return self.partners.get(str(user_id), str(user_id))


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    model_id: str
    db_path: Path
    household: HouseholdConfig
    nudge_hour: int
    nudge_timezone: tzinfo
    metrics_hour: int
    metrics_minute: int
    metrics_weekday: int  # python-telegram-bot JobQueue convention: 0=Sunday..6=Saturday
    # Model provider (design spec §8 / hackathon Phase B). "anthropic" (default)
    # is the original Week-1 direct-API path; "bedrock" routes through Amazon
    # Bedrock instead. anthropic_api_key is only required for "anthropic".
    model_provider: str = "anthropic"
    anthropic_api_key: str | None = None
    # Hackathon/AgentCore target (design spec §8).
    # persistence_backend: "sqlite" (default, Week-1) or "dynamodb" (AWS-backed,
    # covered by moto tests, now runnable for real once aws_region is set).
    persistence_backend: str = "sqlite"
    dynamodb_table_name: str = "cos_tasks"
    # AWS region, shared by both the Bedrock model calls and the DynamoDB
    # backend — e.g. "eu-central-1". Required when model_provider=bedrock or
    # persistence_backend=dynamodb.
    aws_region: str | None = None
    # Optional named AWS CLI profile (COS_AWS_PROFILE) to use instead of the
    # default credential chain — handy for local dev with `aws configure
    # --profile <name>`. Leave unset in production (e.g. AgentCore's IAM role).
    aws_profile: str | None = None
    # Gateway/brain split (design spec §8, hackathon Phase C). "local"
    # (default) runs the Strands Agent in-process, same as before the split.
    # "agentcore" instead fires each instruction at a deployed Bedrock
    # AgentCore Runtime endpoint (agentcore_runtime_arn, required in that
    # mode) via invoke_agent_runtime — the deployed container sends the
    # Telegram reply itself, as a side effect, same as the local path does.
    agent_mode: str = "local"
    agentcore_runtime_arn: str | None = None


def _load_household(path: Path) -> HouseholdConfig:
    if not path.exists():
        raise FileNotFoundError(
            f"Household config not found at {path}. Copy household.example.json "
            "to household.json (or set COS_HOUSEHOLD_CONFIG) and fill in your "
            "chat_id + partner user ids."
        )
    data = json.loads(path.read_text())
    return HouseholdConfig(chat_id=str(data["chat_id"]), partners={str(k): v for k, v in data["partners"].items()})


def _resolve_timezone(name: str | None) -> tzinfo:
    if name:
        return ZoneInfo(name)
    # No COS_TIMEZONE set — fall back to whatever timezone this machine/server
    # is in. Fine for MVP; if the bot runs somewhere with a different local
    # time than the household (e.g. a UTC server), set COS_TIMEZONE to an IANA
    # name (e.g. "Europe/Istanbul") so the morning nudge lands at the right
    # local hour for the household, not the server.
    local_tz = datetime.now().astimezone().tzinfo
    assert local_tz is not None
    return local_tz


def load_settings() -> Settings:
    def require(name: str) -> str:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"Missing required environment variable: {name} (see .env.example)")
        return value

    household_path = Path(os.environ.get("COS_HOUSEHOLD_CONFIG", "household.json"))
    if not household_path.is_absolute():
        household_path = REPO_ROOT / household_path

    db_path = Path(os.environ.get("COS_DB_PATH", "data/cos.db"))
    if not db_path.is_absolute():
        db_path = REPO_ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    model_provider = os.environ.get("COS_MODEL_PROVIDER", "anthropic").strip().lower()
    if model_provider not in ("anthropic", "bedrock"):
        raise RuntimeError(f"COS_MODEL_PROVIDER must be 'anthropic' or 'bedrock', got: {model_provider!r}")

    aws_region = os.environ.get("COS_AWS_REGION") or None
    if model_provider == "bedrock" and not aws_region:
        raise RuntimeError(
            "COS_MODEL_PROVIDER=bedrock requires COS_AWS_REGION to be set (e.g. eu-central-1)."
        )

    agent_mode = os.environ.get("COS_AGENT_MODE", "local").strip().lower()
    if agent_mode not in ("local", "agentcore"):
        raise RuntimeError(f"COS_AGENT_MODE must be 'local' or 'agentcore', got: {agent_mode!r}")
    agentcore_runtime_arn = os.environ.get("COS_AGENTCORE_RUNTIME_ARN") or None
    if agent_mode == "agentcore" and not agentcore_runtime_arn:
        raise RuntimeError("COS_AGENT_MODE=agentcore requires COS_AGENTCORE_RUNTIME_ARN to be set.")

    return Settings(
        telegram_bot_token=require("TELEGRAM_BOT_TOKEN"),
        model_id=os.environ.get("COS_MODEL_ID", "claude-haiku-4-5"),
        db_path=db_path,
        household=_load_household(household_path),
        nudge_hour=int(os.environ.get("COS_NUDGE_HOUR", "9")),
        nudge_timezone=_resolve_timezone(os.environ.get("COS_TIMEZONE")),
        metrics_hour=int(os.environ.get("COS_METRICS_HOUR", "10")),
        metrics_minute=int(os.environ.get("COS_METRICS_MINUTE", "0")),
        metrics_weekday=int(os.environ.get("COS_METRICS_WEEKDAY", "0")),
        model_provider=model_provider,
        anthropic_api_key=(require("ANTHROPIC_API_KEY") if model_provider == "anthropic" else os.environ.get("ANTHROPIC_API_KEY") or None),
        persistence_backend=os.environ.get("COS_PERSISTENCE_BACKEND", "sqlite"),
        dynamodb_table_name=os.environ.get("COS_DYNAMODB_TABLE", "cos_tasks"),
        aws_region=aws_region,
        aws_profile=os.environ.get("COS_AWS_PROFILE") or None,
        agent_mode=agent_mode,
        agentcore_runtime_arn=agentcore_runtime_arn,
    )
