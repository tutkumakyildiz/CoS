# IAM policy templates

Reference policies used to run CoS on Bedrock AgentCore Runtime. Applied by hand via the AWS console/CLI — not consumed automatically by any code in this repo.

**Before using:** replace every `123456789012` placeholder with your own AWS account id, and adjust the `eu-central-1` region / `cos_brain-*` / `cos_tasks` / `cos-agentcore-execution-role` resource names if yours differ.

- `agentcore-trust-policy.json` — trust policy for the AgentCore execution role (who can assume it).
- `agentcore-permissions-policy.json` — permissions policy attached to that execution role (logs, ECR pull, X-Ray, Bedrock model invocation, DynamoDB access — all scoped to specific resources, not `*`).
- `cos-user-passrole-policy.json` — lets the deploying IAM user pass the execution role to AgentCore, and only that role.
- `cos-user-role-management-policy.json` — lets the deploying IAM user create/update/delete only the `cos-agentcore-execution-role`, not arbitrary roles.

### Gateway (ECS Fargate — see `deploy/gateway/README.md`)

Two roles needed, both trusted by `ecs-tasks.amazonaws.com` (use `gateway-execution-role-trust-policy.json` as the trust policy for both — same principal, different permissions attached):

- `gateway-execution-role-trust-policy.json` — trust policy for both the execution role and the task role below.
- `gateway-execution-role-permissions-policy.json` — attached to `cos-gateway-execution-role` (used by ECS itself, not app code): ECR pull scoped to the `cos-gateway` repo only, CloudWatch Logs write scoped to `/ecs/cos-gateway` only, Secrets Manager read scoped to the one gateway bot-token secret only.
- `gateway-task-role-policy.json` — attached to `cos-gateway-task-role` (used by the running app code): only `bedrock-agentcore:InvokeAgentRuntime` on the specific brain runtime ARN — no direct Bedrock/DynamoDB access, since in `COS_AGENT_MODE=agentcore` the gateway never touches those directly.

### Web dashboard (ECS Fargate + ALB — see `deploy/webapp/README.md`; App Runner was the original plan but got account-blocked, see that doc)

- `webapp-instance-role-policy.json` — one role (`cos-webapp-instance-role`) used as **both** the ECS execution role and task role for the webapp's task definition (ECS allows the same role in both fields — simpler than maintaining two, and this role's permissions already cover both duties): read-only DynamoDB (`GetItem`/`Query` on `cos_tasks`), Secrets Manager read scoped to the webapp's own two secrets (password, session key) — needed both by ECS itself (to resolve the task definition's `secrets` field) and conceptually by the app — `ecs:DescribeServices`/`ecs:UpdateService` scoped to the gateway's service only (powers the status/restart panel), plus ECR pull scoped to the `cos-webapp` repo and CloudWatch Logs write scoped to `/ecs/cos-webapp` (the two execution-role duties App Runner would otherwise have handled itself).

### GitHub Actions (OIDC — see `.github/workflows/deploy-gateway.yml`)

Lets the gateway's deploy workflow authenticate to AWS without any stored long-lived credentials — it exchanges a short-lived GitHub-issued OIDC token for temporary AWS credentials via `sts:AssumeRoleWithWebIdentity`. This matters more once this repo goes public: nothing static sits in a repo secret for a leaky workflow or a compromised third-party action to exfiltrate.

- `github-actions-oidc-trust-policy.json` — trust policy for a new `cos-github-actions-deploy-role`. Scoped narrowly on purpose: only workflow runs on this exact repo (`tutkumakyildiz/CoS`) triggered from the `main` branch ref can assume it — a workflow run from a fork PR, or from any other branch, cannot, regardless of what the workflow file says.
- `github-actions-gateway-deploy-permissions-policy.json` — attached to that role: `ecr:GetAuthorizationToken` (unavoidably account-wide — AWS doesn't support resource-scoping this one action), image push scoped to the `cos-gateway` ECR repo only, and `ecs:UpdateService`/`ecs:DescribeServices` scoped to the `cos-gateway` service only. Nothing else — this role can't touch DynamoDB, Bedrock, Secrets Manager, or any other service.

One-time setup (console or CLI, same "Claude drafts the policy JSON, the account owner applies it" convention as everything else in this directory):

1. Create the OIDC identity provider for GitHub Actions, if this AWS account doesn't already have one (`aws iam list-open-id-connect-providers` to check first):
   ```bash
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com \
     --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
   ```
2. Create `cos-github-actions-deploy-role` from `github-actions-oidc-trust-policy.json` (trust policy) with `github-actions-gateway-deploy-permissions-policy.json` attached (permissions policy).
3. Set the role's ARN as a **repo variable** (not a secret — the ARN itself isn't sensitive; the trust policy above is what actually restricts who can use it): Settings → Secrets and variables → Actions → Variables → `GATEWAY_DEPLOY_ROLE_ARN`, or `gh variable set GATEWAY_DEPLOY_ROLE_ARN --body "arn:aws:iam::<account-id>:role/cos-github-actions-deploy-role"`.
4. Protect the `main` branch (require PRs, require the `CI / test` status check, disallow force pushes) — this is what makes reaching the workflow's `push` trigger imply "this code went through review," and is the other half of this setup's security model alongside the trust policy above.

### One-time grants needed on the deploying IAM user (`cos`) before the gateway/webapp rollout

The `cos` user was deliberately created with only Bedrock/DynamoDB/ECR/CloudWatch-Logs access and zero IAM permissions (see project history) — none of that covers ECS, Secrets Manager, or creating the three new roles above. Confirmed via a real `AccessDenied` on `iam:CreateRole`, not a tool-side restriction. Everything below can be applied in one console pass rather than trickling in one grant at a time:

1. **Attach two AWS-managed policies to the `cos` user** (IAM console → Users → `cos` → Add permissions → Attach policies directly), matching the same broad-managed-policy pattern already used for Bedrock/DynamoDB/ECR/Logs:
   - `AmazonECS_FullAccess` — needed for the gateway's cluster/task-definition/service.
   - `SecretsManagerReadWrite` — needed for the gateway's bot-token secret and the webapp's password/session secrets.
2. **Either** create the three roles yourself from the templates above (fastest, no further grants needed), **or** attach these two custom policies to let Claude create them via CLI instead:
   - `cos-user-gateway-webapp-role-management-policy.json` — create/update/delete only `cos-gateway-execution-role`, `cos-gateway-task-role`, `cos-webapp-instance-role`.
   - `cos-user-gateway-webapp-passrole-policy.json` — pass only those same three roles, each scoped to the one service that's allowed to use it (`ecs-tasks.amazonaws.com` for the two gateway roles, `tasks.apprunner.amazonaws.com` for the webapp role).
