# AgentCore Runtime deployable image — the "brain" half of the hackathon
# gateway/brain split (design spec §8). This packages src/cos/runtime_entrypoint.py,
# the BedrockAgentCoreApp/@app.entrypoint adapter around cos.brain.handle_payload.
#
# AgentCore Runtime requires linux/arm64 images. Build with:
#   docker buildx build --platform linux/arm64 -t cos-agentcore-brain .
#
# Secrets (TELEGRAM_BOT_TOKEN, model/AWS config) are NOT baked in here — they're
# passed via AgentCore's environmentVariables at deploy time (see docs/deploy notes).
# household.json is baked in (not a secret, just chat/user id mappings) since
# config.py reads it from a file path, not an env var.

FROM --platform=linux/arm64 python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY household.json ./household.json

RUN pip install --no-cache-dir ".[agentcore]"

# config.py resolves relative paths (COS_HOUSEHOLD_CONFIG, COS_DB_PATH) against
# a REPO_ROOT computed from cos/config.py's own file depth — correct when
# running from a source checkout, but wrong once installed as a package into
# site-packages (as this image does). Absolute paths bypass that entirely.
ENV COS_HOUSEHOLD_CONFIG=/app/household.json
ENV COS_DB_PATH=/app/data/cos.db

EXPOSE 8080

CMD ["python", "-m", "cos.runtime_entrypoint"]
