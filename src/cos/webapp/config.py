"""Web dashboard configuration — deliberately separate from cos.config's
Settings rather than reusing it directly: the webapp needs a different,
smaller set of env vars (no TELEGRAM_BOT_TOKEN/ANTHROPIC_API_KEY/model
config — it never touches Telegram or the model), plus a few webapp-only
ones (login password, session signing key, the gateway's ECS cluster/service
names for the status panel). Reuses cos.config.load_household for the
partners mapping, so household.json stays the single source of truth for
display names.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cos.config import REPO_ROOT, HouseholdConfig, load_household
from cos.persistence.base import TaskStoreBackend


@dataclass(frozen=True)
class WebappSettings:
    household: HouseholdConfig
    webapp_password: str
    session_secret: str
    persistence_backend: str = "dynamodb"
    dynamodb_table_name: str = "cos_tasks"
    db_path: Path = Path("data/cos.db")  # only used when persistence_backend == "sqlite"
    aws_region: str | None = None
    aws_profile: str | None = None
    ecs_cluster: str = "cos-cluster"
    ecs_service: str = "cos-gateway"


def load_webapp_settings() -> WebappSettings:
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

    return WebappSettings(
        household=load_household(household_path),
        webapp_password=require("COS_WEBAPP_PASSWORD"),
        session_secret=require("COS_WEBAPP_SESSION_SECRET"),
        persistence_backend=os.environ.get("COS_PERSISTENCE_BACKEND", "dynamodb"),
        dynamodb_table_name=os.environ.get("COS_DYNAMODB_TABLE", "cos_tasks"),
        db_path=db_path,
        aws_region=os.environ.get("COS_AWS_REGION") or None,
        aws_profile=os.environ.get("COS_AWS_PROFILE") or None,
        ecs_cluster=os.environ.get("COS_ECS_CLUSTER", "cos-cluster"),
        ecs_service=os.environ.get("COS_ECS_SERVICE", "cos-gateway"),
    )


def build_backend(settings: WebappSettings) -> TaskStoreBackend:
    """Not reusing cos.persistence.get_backend's process-cached factory —
    that one takes a full cos.config.Settings, which WebappSettings
    deliberately isn't (see module docstring). Same backend classes,
    constructed directly instead."""
    if settings.persistence_backend == "sqlite":
        from cos.db import init_db
        from cos.persistence.sqlite_backend import SqliteTaskStoreBackend

        init_db(settings.db_path)
        return SqliteTaskStoreBackend()
    if settings.persistence_backend == "dynamodb":
        from cos.persistence.dynamodb_backend import DynamoDBTaskStoreBackend

        return DynamoDBTaskStoreBackend(
            table_name=settings.dynamodb_table_name,
            region_name=settings.aws_region,
            profile_name=settings.aws_profile,
        )
    raise ValueError(f"Unknown COS_PERSISTENCE_BACKEND: {settings.persistence_backend!r} (expected 'sqlite' or 'dynamodb')")
