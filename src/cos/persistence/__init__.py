"""Persistence backend selection. The deployed path needs DynamoDB instead
of local SQLite, since AgentCore Runtime containers are ephemeral.
`get_backend` picks the implementation from Settings; task_store.py's tools
only ever see `TaskStoreBackend`, never raw SQL or DynamoDB calls.
"""

from __future__ import annotations

from cos.config import Settings
from cos.persistence.base import TaskStoreBackend
from cos.persistence.sqlite_backend import SqliteTaskStoreBackend

_backends: dict[str, TaskStoreBackend] = {}


def get_backend(settings: Settings) -> TaskStoreBackend:
    """Get (or lazily build) the configured persistence backend, cached per
    process — same one-instance-per-process pattern as agent.py's _agents."""
    key = settings.persistence_backend
    if key in _backends:
        return _backends[key]

    backend: TaskStoreBackend
    if key == "sqlite":
        backend = SqliteTaskStoreBackend()
    elif key == "dynamodb":
        # Imported lazily so pure-local/sqlite usage never needs boto3 to
        # even be importable, only installed.
        from cos.persistence.dynamodb_backend import DynamoDBTaskStoreBackend

        backend = DynamoDBTaskStoreBackend(
            table_name=settings.dynamodb_table_name,
            region_name=settings.aws_region,
            profile_name=settings.aws_profile,
        )
    else:
        raise ValueError(f"Unknown COS_PERSISTENCE_BACKEND: {key!r} (expected 'sqlite' or 'dynamodb')")

    _backends[key] = backend
    return backend
