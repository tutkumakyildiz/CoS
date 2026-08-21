# Web dashboard deployable image — read-only task list + gateway
# status/restart panel (see README "Web dashboard"). Runs behind AWS App
# Runner: a managed HTTPS endpoint, no ALB/target group to maintain, a good
# fit for a low-traffic two-person internal tool.
#
# Build for linux/arm64, same toolchain as the gateway/brain images:
#   docker buildx build --platform linux/arm64 -f deploy/webapp/Dockerfile -t cos-webapp .
#
# COS_WEBAPP_PASSWORD / COS_WEBAPP_SESSION_SECRET are NOT baked in — App
# Runner resolves them from Secrets Manager into plain env vars at
# container start, same mechanism ECS's task-definition `secrets` field uses
# for the gateway's TELEGRAM_BOT_TOKEN.
#
# household.json IS baked in (display names only, same reasoning as the
# gateway/brain images) — private ECR only, never a public registry.

FROM --platform=linux/arm64 python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY household.json ./household.json

RUN pip install --no-cache-dir ".[webapp]"

ENV COS_HOUSEHOLD_CONFIG=/app/household.json

EXPOSE 8080

CMD ["python", "-m", "cos.webapp"]
