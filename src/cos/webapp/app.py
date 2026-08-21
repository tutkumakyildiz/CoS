"""FastAPI app factory for the web dashboard — task list + bot status/restart,
behind a single shared-password login (see auth.py). Server-rendered
Jinja2 templates, no SPA framework: this is a basic internal tool for one
household's admin, not a customer-facing product (see README).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from cos.webapp.auth import register_auth_routes
from cos.webapp.bot_status import register_status_routes
from cos.webapp.config import WebappSettings, load_webapp_settings
from cos.webapp.tasks_view import register_tasks_routes

_PACKAGE_DIR = Path(__file__).resolve().parent


def create_app(settings: WebappSettings | None = None) -> FastAPI:
    settings = settings or load_webapp_settings()

    app = FastAPI(title="CoS Dashboard")
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=False)

    templates = Jinja2Templates(directory=str(_PACKAGE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_PACKAGE_DIR / "static")), name="static")

    register_auth_routes(app, templates, settings)
    register_tasks_routes(app, templates, settings)
    register_status_routes(app, templates, settings)

    return app
