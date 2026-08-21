# Web dashboard deployment (AWS App Runner)

Reference commands for hosting the read-only task list + bot status/restart panel on AWS App Runner. Applied by hand — same convention as `deploy/gateway/` and `deploy/iam/`.

**Before using:** replace `123456789012` with your own AWS account id, and adjust region/resource names if yours differ from `eu-central-1` / `cos-webapp`. Every `aws` command below also needs `--profile cos-hackathon` (or `export AWS_PROFILE=cos-hackathon` once per shell session) — the deploying IAM user's credentials live under that named profile, not `default` — see `deploy/gateway/README.md`'s note on this for why.

## Status (2026-08-21): not yet deployed — paused, decision pending

Everything up through "Build and push" below is done: `cos-webapp` ECR repo created, image built and pushed, `cos-webapp-instance-role` IAM role created with its permissions policy applied (now covers both App Runner instance-role duties and ECS execution/task-role duties — see `deploy/iam/README.md`), both Secrets Manager secrets created.

**Blocked on two different paths, in order tried:**
1. **App Runner** (this doc's original plan): `aws apprunner list-services` returns `SubscriptionRequiredException` — account-wide (confirmed in two regions), not IAM-permission-related. AWS hasn't activated App Runner for this account yet. Needs either a console visit to trigger activation, or an AWS Support request — unresolved as of this writing.
2. **ECS Fargate + ALB** (attempted as a fallback when App Runner stayed blocked): got as far as creating a target group, an ALB security group, and a task security group — then `aws elbv2 create-load-balancer` hit `AccessDenied` on `iam:CreateServiceLinkedRole`, because this account has never had an ALB before and creating the very first one triggers a one-time service-linked-role bootstrap that the `cos` user isn't permitted to do. A narrow, one-time policy for exactly this (`deploy/iam/cos-user-elb-service-linked-role-policy.json`) was drafted but **not applied** — user chose to pause here rather than grant it. The target group was cleaned up; two now-orphaned (harmless, no cost) security groups — `cos-webapp-alb-sg` and `cos-webapp-task-sg` — couldn't be deleted (`cos` user also lacks `ec2:DeleteSecurityGroup`) and are still sitting unused in the VPC.

**Also considered, not chosen:** exposing the ECS task's public IP directly with no load balancer at all (works immediately, zero new grants, but plain HTTP and a public IP that changes on every task restart) — offered as an option, user paused before deciding.

**When resuming:** ask the user which path they want (retry App Runner activation, grant the one ELB service-linked-role policy and finish the ALB path, or go with the direct-public-IP no-ALB option) rather than assuming. The code/tests/Docker image are unaffected by which hosting path gets chosen — only the last mile (how inbound HTTP reaches the container) differs.

## Why App Runner, not ECS + ALB (the original reasoning, before the account-activation block)

## Why App Runner, not ECS + ALB

Unlike the gateway, this service *does* need inbound HTTP — but it's low-traffic (one household's admin, occasionally). App Runner gives a managed HTTPS endpoint, auto-restart, and no ALB/target group to stand up or pay for (~$16/mo saved vs. ECS+ALB) — the leanest AWS-native option that still gets a real public URL with TLS.

## One-time setup

```bash
aws ecr create-repository --repository-name cos-webapp --region eu-central-1

# Two secrets: the login password and the session-signing key. Generate a
# real random session secret rather than typing one — e.g.:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
aws secretsmanager create-secret --name cos/webapp/password \
  --secret-string "<a real password, not the example below>" --region eu-central-1
aws secretsmanager create-secret --name cos/webapp/session-secret \
  --secret-string "<output of the token_urlsafe command above>" --region eu-central-1
```

Create the App Runner instance role from `deploy/iam/webapp-instance-role-policy.json` via the console (read-only `cos_tasks` access, read access to the two secrets above, `ecs:DescribeServices`/`UpdateService` scoped to the gateway's specific service — powers the status/restart panel).

## Build and push

```bash
docker buildx build --platform linux/arm64 -f deploy/webapp/Dockerfile \
  -t 123456789012.dkr.ecr.eu-central-1.amazonaws.com/cos-webapp:latest . --push
```

## Create the App Runner service

Via the console (App Runner → Create service → Container registry → point at the `cos-webapp` ECR image):
- Port: `8080`.
- Instance role: the one created above.
- Environment variables (plaintext, non-secret): `COS_AWS_REGION=eu-central-1`, `COS_PERSISTENCE_BACKEND=dynamodb`, `COS_DYNAMODB_TABLE=cos_tasks`, `COS_HOUSEHOLD_CONFIG=/app/household.json`, `COS_ECS_CLUSTER=cos-cluster`, `COS_ECS_SERVICE=cos-gateway`.
- Secrets (resolved by App Runner into env vars at container start, same as the gateway's `TELEGRAM_BOT_TOKEN`): `COS_WEBAPP_PASSWORD` → `cos/webapp/password`, `COS_WEBAPP_SESSION_SECRET` → `cos/webapp/session-secret`.

Or via the CLI with `aws apprunner create-service` — the console flow above is simpler for a one-time setup and is the recommended path here.

## Redeploying after a code change

```bash
docker buildx build --platform linux/arm64 -f deploy/webapp/Dockerfile \
  -t 123456789012.dkr.ecr.eu-central-1.amazonaws.com/cos-webapp:latest . --push
aws apprunner start-deployment --service-arn <your App Runner service ARN> --region eu-central-1
```

## Verifying

1. Visit the App Runner service's HTTPS URL — should redirect to `/login`.
2. Wrong password → rejected. Right password → `/tasks`.
3. `/tasks` shows real open + done tasks with correct partner display names (cross-check a couple of known real tasks).
4. `/status` shows the gateway's ECS service as running; clicking restart triggers a visible ECS deployment (check `aws ecs describe-services --cluster cos-cluster --services cos-gateway`), and afterward exactly one gateway task is running again with no 409 conflicts in its logs.
