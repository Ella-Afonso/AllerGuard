# Scheduled infrastructure proof

Template validated by AWS; deployment attempted and rolled back on 2026-09-13.
The applied Lambda concurrency quota in eu-west-2 is 10. AWS requires 10
unreserved executions, so reserving one fails. A quota request for 20 was also
rejected because that API requires a value above its default 1,000. No increase
was submitted successfully. Keep the serial constraint; do not remove it to
make deployment pass. No full-cycle AWS invocation ran.

Four tables with prefix `allerguard-cycle-proof-20260913` remain (business,
ledger, audit, queue); only the fictional business was seeded. The package was
uploaded under `allerguard-cycle-proof/20260913/cycle.zip` in the existing
AgentCore deployment bucket. Stack `allerguard-cycle-proof` is ROLLBACK_COMPLETE.
Its Lambda/role/logs were rolled back; no schedule is active. The pre-existing
hello runtime/invoker was untouched. Retained tables can incur storage charges.

This wraps the existing cycle, uses dedicated synthetic-business tables, and
performs no external notifications or owner decisions.

The CloudFormation template starts with its EventBridge rule disabled. Keep the
existing AgentCore hello runtime and invoker untouched. Provision four dedicated
tables with the existing inventory, alert-ledger, audit, and escalation tools;
seed `demo-cafe` before enabling this rule. Never share its ledger with another
business or a browser demo.

Build a Python 3.12 Linux x86_64 ZIP containing `src/`, dependencies from
`requirements-linux.lock`, and `fixtures/cycle.json` generated using
`src.tools.surface_files.write_replay_feed`. Use Linux wheels, not the Windows
virtual environment. Windows pip environment markers selected pywin32 even with
`--platform`; the lock resolves the installed dependency graph for Linux and
is installed with `--no-deps`. Reproduction from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: --target artifacts/cycle-package -r infra/cycle/requirements-linux.lock
.\.venv\Scripts\python.exe -m scripts.prepare_cycle_proof package --folder artifacts/cycle-package --archive artifacts/cycle-proof.zip
```

Use a fresh package folder when changing dependency versions. Docker was not
available for local Linux import verification; Lambda import verification remains
open because function creation failed first. Upload the reviewed ZIP to a private S3 code
bucket and supply its bucket/key plus the four dedicated table names to the
template. IAM changes must be reviewed before deploying with CAPABILITY_IAM.

Resume by resolving the account quota through AWS, then deploy a new stack name
(a ROLLBACK_COMPLETE stack cannot be updated). Reuse the untouched proof ledger
only after checking that it remains empty. Never label a manually invoked run as
unattended. Capture a scheduled first run before claiming this proof passed.

The default is explicitly injected proposals, real infrastructure/storage. For
Bedrock, add an independently reviewed policy scoped to the configured EU
inference profile and its destination foundation-model ARNs before selecting
`bedrock`; the default role deliberately has no model permission. No SES/SNS
permission is granted. The handler rejects enabled notifications.

Before enabling the schedule, validate the template in AWS and confirm the
function imports, table schemas, seed and bundled fixtures. Do not consume the
fresh proof ledger with a manual successful cycle. Enable the rule and wait for
its first unattended invocation; capture the EventBridge/Lambda timestamp,
structured `scheduled_cycle` log and persisted audit/queue/watermark read-back.
The next invocation must report `empty`. Disable the rule after capturing proof.

Reserved concurrency is one and both retry policies are zero. A blocked or
uncertain commit raises an error. These settings do not provide exactly-once
delivery or an atomic ledger. Inspect failures before rerunning. Five replay
alerts should produce two silent and three escalated assessments; with
notifications disabled the initial history has eight events, not eleven.

The read-only evidence server can point to these tables using the same environment
configuration: `python -m scripts.serve_dashboard --mode aws-evidence`.
It binds to loopback and rejects all POSTs. It never starts Moto.
