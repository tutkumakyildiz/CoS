# IAM policy templates

Reference policies used to run CoS on Bedrock AgentCore Runtime. Applied by hand via the AWS console/CLI — not consumed automatically by any code in this repo.

**Before using:** replace every `123456789012` placeholder with your own AWS account id, and adjust the `eu-central-1` region / `cos_brain-*` / `cos_tasks` / `cos-agentcore-execution-role` resource names if yours differ.

- `agentcore-trust-policy.json` — trust policy for the AgentCore execution role (who can assume it).
- `agentcore-permissions-policy.json` — permissions policy attached to that execution role (logs, ECR pull, X-Ray, Bedrock model invocation, DynamoDB access — all scoped to specific resources, not `*`).
- `cos-user-passrole-policy.json` — lets the deploying IAM user pass the execution role to AgentCore, and only that role.
- `cos-user-role-management-policy.json` — lets the deploying IAM user create/update/delete only the `cos-agentcore-execution-role`, not arbitrary roles.
