"""GET /tasks — read-only task list/table for the household's dashboard.

Deliberately read-only: no create/edit/delete here. CoS's whole point is
natural-language capture and delegation via Telegram — the dashboard is a
viewer, not a second way to manage tasks. Uses TaskStoreBackend.get_all_tasks
(open + done, unlike the agent-facing get_open_tasks/get_overdue_tasks/
get_due_soon_tasks tools, which are all scoped to open work only) and
resolves owner/created_by Telegram user ids to display names via
household.json's partners mapping, same as bot.py does for chat messages.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from cos.webapp.auth import is_authed
from cos.webapp.config import WebappSettings, build_backend


def register_tasks_routes(app, templates: Jinja2Templates, settings: WebappSettings) -> None:
    backend = build_backend(settings)

    @app.get("/")
    async def index():
        return RedirectResponse("/tasks", status_code=303)

    @app.get("/tasks")
    async def tasks_list(request: Request, status: str | None = None, owner: str | None = None):
        if not is_authed(request):
            return RedirectResponse("/login", status_code=303)

        tasks = backend.get_all_tasks(chat_id=settings.household.chat_id)

        owners = sorted({t.get("owner") for t in tasks if t.get("owner")})
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        if owner:
            tasks = [t for t in tasks if t.get("owner") == owner]

        rows = [
            {
                **t,
                "owner_name": settings.household.name_for(t["owner"]) if t.get("owner") else "Unassigned",
                "created_by_name": settings.household.name_for(t["created_by"]),
            }
            for t in tasks
        ]

        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "rows": rows,
                "owners": [(o, settings.household.name_for(o)) for o in owners],
                "selected_status": status or "",
                "selected_owner": owner or "",
            },
        )
