"""DynamoDB implementation of TaskStoreBackend — the deployed path's
persistence. AgentCore Runtime containers are ephemeral, so the SQLite file
the local/dev path uses isn't reachable from inside one; this replaces it
with a network-reachable, serverless table.

Table layout: partition key `chat_id`, sort key `task_id`. Every query this
backend needs (open tasks, overdue, due-soon, weekly metrics) is scoped to
one chat, so a Query against the partition key covers all of them in one
round trip — no Scan. Status/owner/due_date filtering and sorting happen
client-side on the (small, household-scale) result set, the same tradeoff
SQLite's WHERE/ORDER BY make implicitly at this scale. If usage ever
outgrows that, a GSI on (chat_id, status) or (chat_id, due_date) is the next
step — not needed for an MVP household.

Tested against a mocked table (moto — see tests/test_persistence_dynamodb.py),
no real AWS account needed. Also live-verified against a real deployed
table (see README "Status").
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from cos.persistence.base import TaskStoreBackend, grouped_pct

OPEN_STATUSES = ("open", "in_progress")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_table_if_not_exists(resource: Any, table_name: str) -> Any:
    """One-time setup, not a per-request call — run at deploy time (or by a
    test fixture against moto). Idempotent: does nothing if the table
    already exists."""
    existing = {t.name for t in resource.tables.all()}
    if table_name in existing:
        return resource.Table(table_name)

    table = resource.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "chat_id", "KeyType": "HASH"},
            {"AttributeName": "task_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "chat_id", "AttributeType": "S"},
            {"AttributeName": "task_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table


class DynamoDBTaskStoreBackend(TaskStoreBackend):
    def __init__(
        self,
        table_name: str,
        region_name: str | None = None,
        profile_name: str | None = None,
        resource: Any = None,
    ):
        if resource is not None:
            self._resource = resource
        else:
            # Same profile-aware session pattern as agent.py's _build_model,
            # so COS_AWS_PROFILE works consistently for both Bedrock and
            # DynamoDB rather than silently only working for one of them.
            session = boto3.Session(profile_name=profile_name, region_name=region_name)
            self._resource = session.resource("dynamodb")
        self._table = self._resource.Table(table_name)

    def _query_chat(self, chat_id: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        resp = self._table.query(KeyConditionExpression=Key("chat_id").eq(chat_id))
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = self._table.query(
                KeyConditionExpression=Key("chat_id").eq(chat_id),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
        return [dict(i) for i in items]

    def create_task(
        self,
        *,
        chat_id: str,
        title: str,
        category: str,
        created_by: str,
        due_date: str | None = None,
        owner: str | None = None,
        recurrence: str | None = None,
        source_message: str | None = None,
    ) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = _now()
        item = {
            "chat_id": chat_id,
            "task_id": task_id,
            "title": title,
            "category": category,
            "created_by": created_by,
            "owner": owner,
            "due_date": due_date,
            "status": "open",
            "recurrence": recurrence,
            "source_message": source_message,
            "created_at": now,
            "updated_at": now,
            "last_nudge_at": None,
            "completed_at": None,
        }
        # DynamoDB items can hold explicit NULLs, but skip attributes with no
        # value at all rather than writing a pile of them on every create.
        self._table.put_item(Item={k: v for k, v in item.items() if v is not None})
        return item

    def update_task(self, *, chat_id: str, task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        if fields.get("status") == "done":
            fields = {**fields, "completed_at": now}
        update_fields = {**fields, "updated_at": now}

        expr_names = {f"#{k}": k for k in update_fields}
        expr_values = {f":{k}": v for k, v in update_fields.items()}
        set_expr = "SET " + ", ".join(f"#{k} = :{k}" for k in update_fields)

        try:
            resp = self._table.update_item(
                Key={"chat_id": chat_id, "task_id": task_id},
                UpdateExpression=set_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
                ConditionExpression="attribute_exists(task_id)",
                ReturnValues="ALL_NEW",
            )
        except self._resource.meta.client.exceptions.ConditionalCheckFailedException:
            raise ValueError(f"No task {task_id} found in this chat") from None
        return dict(resp["Attributes"])

    def mark_done(self, *, chat_id: str, task_id: str) -> dict[str, Any]:
        return self.update_task(chat_id=chat_id, task_id=task_id, fields={"status": "done"})

    def get_open_tasks(self, *, chat_id: str, owner: str | None = None) -> list[dict[str, Any]]:
        items = [i for i in self._query_chat(chat_id) if i["status"] in OPEN_STATUSES]
        if owner is not None:
            items = [i for i in items if i.get("owner") == owner]
        items.sort(key=lambda i: (i.get("due_date") is None, i.get("due_date") or "", i.get("created_at") or ""))
        return items

    def get_overdue_tasks(self, *, chat_id: str) -> list[dict[str, Any]]:
        today = date.today().isoformat()
        items = [
            i
            for i in self._query_chat(chat_id)
            if i["status"] in OPEN_STATUSES and i.get("due_date") and i["due_date"] < today
        ]
        items.sort(key=lambda i: i["due_date"])
        return items

    def get_due_soon_tasks(self, *, chat_id: str, days: int = 2) -> list[dict[str, Any]]:
        today = date.today()
        today_iso = today.isoformat()
        horizon_iso = (today + timedelta(days=days)).isoformat()
        items = [
            i
            for i in self._query_chat(chat_id)
            if i["status"] in OPEN_STATUSES and i.get("due_date") and today_iso <= i["due_date"] <= horizon_iso
        ]
        items.sort(key=lambda i: i["due_date"])
        return items

    def get_all_tasks(self, *, chat_id: str) -> list[dict[str, Any]]:
        items = self._query_chat(chat_id)
        items.sort(key=lambda i: i.get("created_at") or "", reverse=True)
        return items

    def get_weekly_metrics(self, *, chat_id: str, days: int = 7) -> dict[str, Any]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        since = (date.today() - timedelta(days=days)).isoformat()
        items = self._query_chat(chat_id)

        captured_by_owner: dict[str, int] = {}
        for i in items:
            if (i.get("created_at") or "") >= cutoff:
                captured_by_owner[i["created_by"]] = captured_by_owner.get(i["created_by"], 0) + 1

        completed_by_owner: dict[str, int] = {}
        nudge_flags: list[str | None] = []
        for i in items:
            if i["status"] == "done" and (i.get("completed_at") or "") >= cutoff:
                owner_key = i.get("owner") or "unassigned"
                completed_by_owner[owner_key] = completed_by_owner.get(owner_key, 0) + 1
                nudge_flags.append(i.get("last_nudge_at"))

        captured_total = sum(captured_by_owner.values())
        completed_total = sum(completed_by_owner.values())
        resolved_without_nudge = sum(1 for flag in nudge_flags if flag is None)
        resolved_with_nudge = len(nudge_flags) - resolved_without_nudge

        return {
            "since": since,
            "captured_total": captured_total,
            "captured_by_owner": captured_by_owner,
            "captured_pct_by_owner": grouped_pct(captured_by_owner, captured_total),
            "completed_total": completed_total,
            "completed_by_owner": completed_by_owner,
            "completed_pct_by_owner": grouped_pct(completed_by_owner, completed_total),
            "resolved_without_nudge": resolved_without_nudge,
            "resolved_with_nudge": resolved_with_nudge,
            "resolved_without_nudge_pct": (
                round(100 * resolved_without_nudge / completed_total, 1) if completed_total else 0.0
            ),
        }
