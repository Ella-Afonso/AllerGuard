# AllerGuard

AllerGuard is an autonomous agent system being developed for small UK food businesses. It is designed to monitor Food Standards Agency (FSA) recall alerts against a business’s inventory, maintain a daily safety record, and surface decisions requiring human review.

## Status

| Area | Verification state |
|---|---|
| **Step 7 — Matcher (live Bedrock)** | Verified. Five labelled live fixture tests passed against real Bedrock in `eu-west-2`. This is separate from Step 8 audit storage. |
| **Step 8 — Gate + audit (offline)** | Verified. Deterministic gate, append-only audit boundary, and `process_alert` seam exercised with Moto and injected proposals (`tests/test_gate.py`, `tests/test_audit.py`, `tests/test_process_alert.py`, `tests/test_audit_demo.py`). |
| **Step 8 — Offline test suite** | Verified (2026-09-10): **197 passed**, **5 live Bedrock cases intentionally skipped** (`ALLERGUARD_LIVE_BEDROCK` unset), **1 third-party Pydantic warning** (bedrock-agentcore). `ruff check src tests scripts` passed; `ruff format --check src tests scripts` — **65 files** formatted; `mypy src` passed (**40 source files**). |
| **Step 8 — Live DynamoDB audit-tool verification** | Verified (2026-09-10). Real table `allerguard-audit` in `eu-west-2`; audit-tool append/read, duplicate protection, separate-process persistence, and preservation of synthetic error/recovery events under a scoped assumed runtime role used **only for live verification** — not attached to production compute. Synthetic records only; operator guide in [`infra/audit/README.md`](infra/audit/README.md). |
| **Step 8 — Not verified on live AWS** | Live `process_alert` → DynamoDB integration, live Bedrock end-to-end execution for Step 8, and AgentCore deployment are **not** verified here. |
| **Supervisor, approval, notification, Action-Drafter, watermark, dashboard** | **Not implemented.** The spine stops after match → gate → audit. |

The offline evidence demo runs the real matcher validation path, deterministic
gate, and audit append code. Its HTML report is a read-only snapshot of stored
rows — not an approval interface and not proof that an owner was notified.

## Intended workflow

```text
Scheduled monitoring
  → inventory matching
  → deterministic escalation gate
  → human review
  → append-only audit trail
```

The demonstration will use a fictional business and synthetic or public data only.

## Development setup

### Requirements

- Git
- Python 3.12 
- AWS CLI v2 for AWS access
- An AWS identity with permission to invoke the selected Bedrock model

### Create a development environment

Run these commands from the repository root. Create the virtual environment with an installed Python 3.12 

### Use an existing environment

If `.venv` already exists, activate it — do not recreate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Verify the interpreter and the core dependencies:

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
python -c "import strands, boto3, pydantic; print('Core imports OK')"
```

The expected Python version is `3.12.x`, and the executable path should point inside the project's `.venv`.

These commands install dependencies without locking exact versions. A reproducible dependency specification remains foundation work.

## AWS configuration

The verified Bedrock request uses Europe (London), `eu-west-2`, as its source region.

In an authenticated PowerShell session, set:

```powershell
$env:AWS_PROFILE = 'allerguard-dev'
$env:AWS_REGION = 'eu-west-2'
$env:AWS_DEFAULT_REGION = 'eu-west-2'
$env:ALLERGUARD_BEDROCK_MODEL_ID = 'eu.anthropic.claude-sonnet-4-5-20250929-v1:0'
```

`allerguard-dev` is the local AWS profile name used during development. Replace it if your configured profile has a different name.

These environment variables select a profile and region; they do not sign you in.

Verify the active AWS identity:

```powershell
aws sts get-caller-identity
```

### Verified Bedrock configuration

- Model: Anthropic Claude Sonnet 4.5
- Source region: `eu-west-2`
- Inference profile ID: `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`

This is an EU cross-region inference profile. Selecting London as the source region does not mean every inference request is processed in London.

Model access depends on the AWS account and its permissions. The profile was successfully invoked in the development account.

Never commit AWS credentials, session tokens, passwords, or local authentication files.

## Development checks

From the activated `.venv`, run:

```powershell
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy src
python -m pytest
```

The verified offline suite result (2026-09-10): **197 passed**, **5 skipped**
(live Bedrock opt-in only), **1 third-party Pydantic warning**. Live Bedrock
cases remain opt-in via `ALLERGUARD_LIVE_BEDROCK=1`; Step 7 live matcher
verification is separate from the default offline run.

## Step 8: deterministic gate and append-only audit

### Verified behaviour (offline)

- **Deterministic gate** (`src/safety/gate.py`): only an assessed `NO_MATCH` is
  `SILENT`. `POSSIBLE`, `LIKELY`, and `CONFIRMED` all `ESCALATE`.
- **Matcher failures** require review: they produce a `MATCH_ERROR` audit event
  with no invented tier (`tier` and `floor_tier` are null) and `decision =
  ESCALATE`.
- **Append-only application behaviour:** audit writes use conditional
  `PutItem` only; there is no update or delete API in `src/tools/audit.py`.
- **Duplicate retries** read back and return the first stored event when
  assessment identity matches; changed model prose or execution timestamp does
  not overwrite history.
- **Failure and recovery** remain separate historical events: a later successful
  assessment appends `#match_decision` without removing an earlier
  `#match_error` for the same assessment identity.

This is **application-enforced append-only storage**, not WORM or tamper-proof
compliance storage. Deletion protection applies to the DynamoDB table, not to
individual items. A principal with unrestricted `PutItem` could still overwrite
a row outside this code path.

If audit persistence fails, processing raises `AuditPersistenceError` and cannot
return a successful receipt. That is not human notification — approval,
notification, supervisor orchestration, Action-Drafter, and watermark commits
remain future work.

### Offline demonstration

Label: **OFFLINE / INJECTED PROPOSALS / MOTO MEMORY STORE / NO AWS / NO BEDROCK**

The demo uses the real `process_alert` seam with injected proposals passed
through the actual Matcher validation path. Counts are derived from rows read
back through the audit tool (`summarize_audit_entries`), not from expected
fixture outcomes.

**Persistence note:** Moto storage exists only for the running demo process.
Restarting the process starts with an empty store; this does not demonstrate
durable audit storage across restarts or live DynamoDB.

From the repository root with `.venv` activated:

```powershell
# Full scenario — five labelled fixtures, two passes (default --repeat 2)
.\.venv\Scripts\python.exe -m scripts.demo_gate_audit --scenario full --repeat 2 --report artifacts/audit-full.html

# Failure then recovery — simulated matcher error on pass 1, success on pass 2
.\.venv\Scripts\python.exe -m scripts.demo_gate_audit --scenario failure --repeat 2 --report artifacts/audit-recovery.html
```

(`scripts.demo_gate_audit` defaults: `--scenario full`, `--repeat 2`,
`--report artifacts/audit-demo.html`. The failure scenario requires
`--repeat 2` or more.)

**Expected persisted counts — full scenario (after pass 2):**

| Count | Value |
|---|---|
| Stored audit events | 5 |
| Distinct assessments | 5 |
| Silent decision events | 2 (olives, clover seeds fixtures) |
| Requires-review decision events | 3 (walnut ≥ POSSIBLE, mustard ≥ POSSIBLE, Doritos ≥ LIKELY) |
| Assessment error events | 0 |

Pass 2 reuses the same five stored event keys; totals do not increase.

**Expected persisted counts — failure/recovery scenario (after pass 2):**

| Count | Value |
|---|---|
| Stored audit events | 2 |
| Distinct assessments | 1 |
| Assessment error events | 1 |
| Requires-review decision events | 1 |

The original `#match_error` row remains after recovery; recovery adds a separate
`#match_decision` row for the same assessment identity.

Open the generated HTML under `artifacts/` in a browser. The report lists stored
audit events and distinct assessments separately — event count is not the number
of alerts processed, and “requires review” does not mean the owner was notified.

### Live DynamoDB audit-tool verification

This is **live audit persistence verification using synthetic records** through
`src/tools/audit.py` — not a live Bedrock end-to-end run, not live
`process_alert` integration on AWS, and not proof that rows cannot be overwritten
outside the application's conditional `PutItem` path.

**Verified on live AWS (2026-09-10):**

- Table provisioned: default name `allerguard-audit`, region `eu-west-2`, on-demand
  billing, deletion protection enabled, TTL disabled.
- Scoped runtime role `allerguard-audit-runtime` used via temporary assumed-role
  credentials for verification sessions only. The role is **not** attached to
  AgentCore, Lambda, or other production compute today.
- Audit-tool operations confirmed with fictional/synthetic data in isolated
  business namespaces: append and read-back, duplicate protection (`created=false`
  on retry), separate-process persistence, and coexistence of `#match_error` and
  `#match_decision` rows for one assessment identity.

**Explicitly separate from:**

- **Offline Moto demo** above (process-local storage; see persistence note).
- **Step 7 live Bedrock matcher verification** (prior work; five labelled fixtures).
- **Future work:** approval queue, notification, supervisor orchestration, poll
  watermark commits, Action-Drafter, dashboard, and AgentCore deployment with
  production runtime identity wiring.

Operator setup, IAM templates, and table design: [`infra/audit/README.md`](infra/audit/README.md).
Optional `--live` demo mode (`scripts.demo_gate_audit --live`) combines real Bedrock
with DynamoDB and is not required for offline or audit-tool verification.

## Application structure

- `src/agents/` — agent prompts and orchestration
- `src/tools/` — external effects and service integrations
- `src/domain/` — pure data models and matching logic
- `src/safety/` — deterministic escalation decisions
- `src/api/` — API boundary
- `src/runtime/` — runtime entry points
- `fixtures/` — public or synthetic demonstration data
- `web/` — planned dashboard
- `infra/` — deployment configuration
- `tests/` — automated tests as implementation progresses

Implemented components and unfinished integrations are distinguished in the status above.

## Design requirements

The implementation must satisfy these requirements:

- No genuinely relevant recall in the labelled test set may be classified as `NO_MATCH`.
- Uncertain matches must be escalated for human review.
- The escalation gate must use deterministic code and contain no model calls.
- Every processing outcome, including errors, must produce an append-only audit record.
- External side effects must be implemented through tools.
- Replay and live monitoring must share the same processing code path.
- Demonstrations must use fictional, synthetic, or public data.

These remain the full-system acceptance criteria. Passing a finite labelled test
set does not prove universal recall detection or live prompt-injection resistance.

## Tools and AI assistance

Claude Code, Cursor Agent, and OpenAI Codex assisted with planning, implementation,
testing, review, troubleshooting, and documentation. Moto provides offline AWS
emulation for tests and the explicitly labelled offline evidence demo.

The planned application stack includes:

- Python 3.12 with venv and pip
- AWS Strands Agents SDK and Strands Agents Tools
- Amazon Bedrock
- Boto3 with its CRT extra
- Pydantic
- pytest, Ruff, and mypy

This disclosure will be updated as implementation progresses and additional tools or pre-existing code are used.

## Licence

MIT. See [LICENSE](LICENSE).

Historical recall fixtures contain public sector information licensed under the
Open Government Licence v3.0. Source: the UK Food Standards Agency. The café
profile is fictional; no private business or personal data is used.
