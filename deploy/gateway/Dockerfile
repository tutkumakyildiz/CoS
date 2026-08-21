# Gateway deployable image — the "gateway" half of the gateway/brain split
# (see README "Architecture"). This packages src/cos/main.py, i.e. the
# Telegram long-poll listener + daily-nudge/weekly-metrics JobQueue
# schedulers. Runs as an always-on ECS Fargate task (no inbound traffic —
# pure outbound long-poll to Telegram + outbound invoke_agent_runtime calls
# to the deployed brain), NOT a request/response service, so it does not fit
# AgentCore Runtime the way the brain does — see README for why.
#
# Build for linux/arm64 (Graviton, same toolchain as the brain image, cheaper
# than x86_64 on Fargate):
#   docker buildx build --platform linux/arm64 -f deploy/gateway/Dockerfile -t cos-gateway .
#
# TELEGRAM_BOT_TOKEN is NOT baked in — it's resolved from AWS Secrets Manager
# via the ECS task definition's `secrets` field at container start, same
# discipline as any other bearer credential in this project.
#
# household.json IS baked in, same call already made for the brain's image
# and the same reasoning: low-churn data (a chat_id + partners' Telegram
# user ids/display names), not itself a credential, private-ECR-only. Never
# push this image to a public registry.

FROM --platform=linux/arm64 python:3.13-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY household.json ./household.json

# No [agentcore] extra — the gateway never imports bedrock_agentcore
# (that's only runtime_entrypoint.py's job, via cos.brain's invoke_remote
# path, which is plain boto3).
RUN pip install --no-cache-dir .

# Same REPO_ROOT-resolution wrinkle as the brain image: config.py resolves
# relative paths against a REPO_ROOT computed from its own file depth, which
# is wrong once installed into site-packages. Absolute paths bypass it.
ENV COS_HOUSEHOLD_CONFIG=/app/household.json
ENV COS_DB_PATH=/app/data/cos.db

# No EXPOSE — this process takes no inbound connections at all.

CMD ["python", "-m", "cos.main"]
