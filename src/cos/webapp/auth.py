"""Single shared-password gate for the dashboard — no user accounts/roles.
This is an ops console for the household's own admin, not a multi-user
product (see README "Web dashboard" section for the scope call).
"""

from __future__ import annotations

import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from cos.webapp.config import WebappSettings

SESSION_KEY = "cos_authed"


def check_password(submitted: str, settings: WebappSettings) -> bool:
    # Constant-time compare — cheap insurance even for a low-stakes internal
    # tool, and there's no reason not to do it right.
    return hmac.compare_digest(submitted, settings.webapp_password)


def is_authed(request: Request) -> bool:
    return bool(request.session.get(SESSION_KEY))


def register_auth_routes(app, templates: Jinja2Templates, settings: WebappSettings) -> None:
    @app.get("/login")
    async def login_form(request: Request):
        if is_authed(request):
            return RedirectResponse("/tasks", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login_submit(request: Request):
        form = await request.form()
        password = str(form.get("password", ""))
        if check_password(password, settings):
            request.session[SESSION_KEY] = True
            return RedirectResponse("/tasks", status_code=303)
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong password."}, status_code=401
        )

    @app.post("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)
