# AgentCore Runtime deployable image — the "brain" half of the gateway/brain
# split (see README "Architecture"). This packages src/cos/runtime_entrypoint.py,
# the BedrockAgentCoreApp/@app.entrypoint adapter around cos.brain.handle_payload.
#
# AgentCore Runtime requires linux/arm64 images. Build with:
#   docker buildx build --platform linux/arm64 -t cos-agentcore-brain .
#
# Secrets (TELEGRAM_BOT_TOKEN, model/AWS config) are NOT baked in here — they're
# passed via AgentCore's environmentVariables at deploy time.
#
# household.json IS baked in, since config.py reads it from a file path, not
# an env var. It's not a credential, but it does contain real personal data
# once filled in (a real Telegram group chat_id, and partners' real Telegram
# user ids + display names) — treat a built image the same as that file:
# fine to push to a private ECR repo for your own AgentCore deploy, but never
# push it to a public registry (Docker Hub, a public ECR repo, etc.).

FROM --platform=linux/arm64 python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY household.json ./household.json

RUN pip install --no-cache-dir ".[agentcore,calendar]"

# config.py resolves relative paths (COS_HOUSEHOLD_CONFIG, COS_DB_PATH) against
# a REPO_ROOT computed from cos/config.py's own file depth — correct when
# running from a source checkout, but wrong once installed as a package into
# site-packages (as this image does). Absolute paths bypass that entirely.
ENV COS_HOUSEHOLD_CONFIG=/app/household.json
ENV COS_DB_PATH=/app/data/cos.db

EXPOSE 8080

CMD ["python", "-m", "cos.runtime_entrypoint"]
