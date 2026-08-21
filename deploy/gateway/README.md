# Gateway deployment (ECS Fargate)

Reference templates/commands for running the Telegram gateway (`cos.main`) as an always-on ECS Fargate task. Applied by hand via the AWS console/CLI — not consumed automatically by any code in this repo, same convention as `deploy/iam/`.

**Before using:** replace every `123456789012` placeholder with your own AWS account id, and adjust region/resource names if yours differ from `eu-central-1` / `cos-gateway` / `cos-cluster` / `cos_brain-*` / `cos_tasks`.

**Every `aws` command below needs `--profile cos-hackathon`** (or `export AWS_PROFILE=cos-hackathon` once per shell session) — the deploying IAM user's credentials live under that named profile in `~/.aws/credentials`, not `default`. Without it you'll get `Unable to locate credentials` even though the credentials are right there on disk. (`docker buildx build --push` doesn't need this — it reuses a cached ECR auth token from the last time `aws ecr get-login-password --profile cos-hackathon | docker login ...` ran, which stays valid for ~12h.)

## Why ECS Fargate, not AgentCore Runtime

The gateway is a blocking `python-telegram-bot` long-poll process (`app.run_polling()`) plus two `JobQueue.run_daily` scheduled jobs — it needs to stay running 24/7 and holds no inbound HTTP endpoint at all. AgentCore Runtime is a synchronous request/response HTTP service with no support for either of those, which is exactly why this project already splits into a gateway/brain architecture (see the root README's "Architecture" section). The brain deploys to AgentCore; the gateway needs a plain always-on container instead — ECS Fargate, no load balancer (no inbound traffic to receive).

## One-time setup

```bash
# ECR repo (separate from cos-agentcore-brain, for clean IAM scoping)
aws ecr create-repository --repository-name cos-gateway --region eu-central-1

# ECS cluster (Fargate-only)
aws ecs create-cluster --cluster-name cos-cluster --region eu-central-1

# CloudWatch log group
aws logs create-log-group --log-group-name /ecs/cos-gateway --region eu-central-1

# Secrets Manager secret for the bot token (put the real token in yourself,
# e.g. via the console, or --secret-string with the real value substituted)
aws secretsmanager create-secret --name cos/gateway/telegram-bot-token \
  --secret-string "<real TELEGRAM_BOT_TOKEN>" --region eu-central-1
```

Create the two IAM roles from `deploy/iam/gateway-execution-role-*.json` and `deploy/iam/gateway-task-role-policy.json` via the console (per this project's convention: Claude drafts the policy JSON, the account owner creates/applies the actual IAM resources).

## Build and push

```bash
docker buildx build --platform linux/arm64 -f deploy/gateway/Dockerfile \
  -t 123456789012.dkr.ecr.eu-central-1.amazonaws.com/cos-gateway:latest . --push
```

## Register the task definition and create the service

Fill in `task-definition.json`'s placeholders (account id, real `COS_AGENTCORE_RUNTIME_ARN`), then:

```bash
aws ecs register-task-definition --cli-input-json file://deploy/gateway/task-definition.json --region eu-central-1
```

Fill in `service-create-request.json`'s subnet/security-group placeholders (default VPC's public subnets; a security group with **no inbound rules** — the gateway takes no inbound traffic), then create the service with `desiredCount: 0` — this stands up the service/logging/networking without starting a poller yet:

```bash
aws ecs create-service --cli-input-json file://deploy/gateway/service-create-request.json --region eu-central-1
```

## Cutover (avoids the Telegram 409-conflict gotcha)

Two long-pollers sharing one bot token causes Telegram's `getUpdates` to return `Conflict: terminated by other getUpdates request` (already hit and documented in this project's history). Sequence to avoid any overlap:

1. Confirm the local `python -m cos.main` process is the only thing polling: `ps aux | grep cos.main`. Stop it.
2. Scale the ECS service up: `aws ecs update-service --cluster cos-cluster --service cos-gateway --desired-count 1 --region eu-central-1`.
3. Tail the logs and confirm a clean start with no conflict errors:
   `aws logs tail /ecs/cos-gateway --follow --region eu-central-1`
   — look for `CoS listening on chat_id=<id>`, and the absence of any `Conflict` line.
4. Send a real message in the household group; confirm a reply comes back (proves the full ECS → AgentCore brain → DynamoDB → Telegram round trip).
5. Tap a callback button on an existing task; confirm it's handled.
6. Confirm exactly one instance is running: `aws ecs describe-services --cluster cos-cluster --services cos-gateway --region eu-central-1` should show `runningCount: 1`, and `ps aux` locally should show no `cos.main` process.

**Never run local `python -m cos.main` again against the production token while the ECS service is live, and never scale `desiredCount` above 1** — the `minimumHealthyPercent: 0, maximumPercent: 100` deployment config in the service definition means a redeploy stops the old task before starting the new one (a few seconds of downtime, in exchange for guaranteed non-overlap) — do not change this for "redundancy," it would recreate the same conflict.

## Redeploying after a code change

```bash
docker buildx build --platform linux/arm64 -f deploy/gateway/Dockerfile \
  -t 123456789012.dkr.ecr.eu-central-1.amazonaws.com/cos-gateway:latest . --push
aws ecs update-service --cluster cos-cluster --service cos-gateway --force-new-deployment --region eu-central-1
```
