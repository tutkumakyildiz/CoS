"""GET /status — is the gateway's ECS service healthy; POST /status/restart
— force a new deployment. This is the "manage the bot" half of the
dashboard (see README) — deliberately just health + restart, nothing more:
the gateway's own ECS deployment config (minimumHealthyPercent=0,
maximumPercent=100 — see deploy/gateway/README.md) already guarantees a
restart can't create the two-pollers-one-token 409 conflict, so a manual
restart here is safe to expose.
"""

from __future__ import annotations

import boto3
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from cos.webapp.auth import is_authed
from cos.webapp.config import WebappSettings


def _ecs_client(settings: WebappSettings):
    session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
    return session.client("ecs")


def register_status_routes(app, templates: Jinja2Templates, settings: WebappSettings) -> None:
    @app.get("/status")
    async def status_page(request: Request, error: str | None = None, restarted: str | None = None):
        if not is_authed(request):
            return RedirectResponse("/login", status_code=303)

        client = _ecs_client(settings)
        service = None
        try:
            resp = client.describe_services(cluster=settings.ecs_cluster, services=[settings.ecs_service])
            services = resp.get("services", [])
            service = services[0] if services else None
            if service is None and error is None:
                error = f"No service named {settings.ecs_service!r} found in cluster {settings.ecs_cluster!r}."
        except Exception as exc:  # noqa: BLE001 — surface any AWS/API error to the page, not a 500
            error = error or str(exc)

        return templates.TemplateResponse(
            request,
            "status.html",
            {
                "service": service,
                "error": error,
                "restarted": bool(restarted),
                "cluster": settings.ecs_cluster,
                "ecs_service_name": settings.ecs_service,
            },
        )

    @app.post("/status/restart")
    async def restart(request: Request):
        if not is_authed(request):
            return RedirectResponse("/login", status_code=303)

        client = _ecs_client(settings)
        try:
            client.update_service(
                cluster=settings.ecs_cluster, service=settings.ecs_service, forceNewDeployment=True
            )
            return RedirectResponse("/status?restarted=1", status_code=303)
        except Exception as exc:  # noqa: BLE001 — surface the real error rather than swallowing it
            return RedirectResponse(f"/status?error={exc}", status_code=303)
