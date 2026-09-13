# AllerGuard

AllerGuard is an autonomous agent system being developed for small UK food businesses. It is designed to monitor Food Standards Agency (FSA) recall alerts against a business’s inventory, maintain a daily safety record, and surface decisions requiring human review.

## Status

| Area | Verification state |
|---|---|
| **Matcher (live Bedrock)** | Verified. Five labelled live fixture tests passed against real Bedrock in `eu-west-2`. This is separate from audit storage. |
| **Gate + audit (offline)** | Verified. Deterministic gate, append-only audit boundary, and `process_alert` seam exercised with Moto and injected proposals (`tests/test_gate.py`, `tests/test_audit.py`, `tests/test_process_alert.py`, `tests/test_audit_demo.py`). |
| **Offline test suite baseline** | Verified (2026-09-10): **197 passed**, **5 live Bedrock cases intentionally skipped** (`ALLERGUARD_LIVE_BEDROCK` unset), **1 third-party Pydantic warning** (bedrock-agentcore). |
| **Current offline suite** | Verified (2026-09-12): **361 passed**, **6 paid Bedrock cases deselected**, **1 third-party Pydantic warning**. Ruff check passed; format check reported 88 files already formatted; mypy passed across 48 source files. |
| **Live DynamoDB audit-tool verification** | Verified (2026-09-10). Real table `allerguard-audit` in `eu-west-2`; audit-tool append/read, duplicate protection, separate-process persistence, and preservation of synthetic error/recovery events under a scoped assumed runtime role used **only for live verification** — not attached to production compute. Synthetic records only; operator guide in [`infra/audit/README.md`](infra/audit/README.md). |
| **Not verified on live AWS** | Live `process_alert` → DynamoDB integration, live Bedrock end-to-end execution for the audit integration, and AgentCore deployment are **not** verified here. |
| **Action-Drafter and pending queue** | Implemented: validated four-field drafts, explicit model/fallback provenance, conditional first-write-wins queue and queued audit. Offline integration verified; one live Doritos drafter fixture passed separately. Live queue/process_alert integration on DynamoDB has not been verified. |
| **Owner notification and approval path** | Implemented and offline verified: disabled-by-default notification boundary, SES/SNS provider truth, simulated notification orchestration, immutable approve/edit/decline decisions, read-only CLI, and report labels. No live email or inbox receipt is claimed. |
| **Supervisor and monitoring cycle (offline)** | Verified with Moto: deterministic five-alert batch, two silent decisions, three escalations, persisted watermark commit, replay returning zero, crash/partial-write recovery, and guarded Strands agents-as-tools wiring. Live scheduler and production attachment remain unverified. |

The offline evidence demo runs the real matcher validation path, deterministic
gate, and audit append code. Its HTML report is a read-only snapshot of stored
rows — not an approval interface and not proof that an owner was notified.

## Intended workflow

```text
Scheduled monitoring
  → inventory matching
  → deterministic escalation gate
  → owner notification
  → human review
  → approve / edit / decline
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

The current verified offline suite result (2026-09-12): **361 passed**, **6 paid
Bedrock cases deselected**, and **1 third-party Pydantic warning**. Ruff check
passed; format check reported 88 files already formatted; mypy passed across
48 source files. Live Bedrock cases remain opt-in
via `ALLERGUARD_LIVE_BEDROCK=1`; Live matcher verification is separate
from the default offline run.

## deterministic gate and append-only audit

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
return a successful receipt. The runtime also persists a validated drafted/fallback
action pack and pending escalation. The runtime also adds an explicit owner-notification
boundary and immutable owner decision records; it does not execute customer or
stock actions. An offline deterministic monitoring cycle and guarded supervisor
path now commit the ledger watermark after persisted outcomes; live AWS
scheduling and production attachment remain unverified.

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
| Stored audit events | 8 (5 match decisions + 3 queued events) |
| Distinct assessments | 5 |
| Silent decision events | 2 (olives, clover seeds fixtures) |
| Requires-review decision events | 3 (walnut ≥ POSSIBLE, mustard ≥ POSSIBLE, Doritos ≥ LIKELY) |
| Assessment error events | 0 |

Pass 2 reuses the same eight stored event keys; totals do not increase.

**Expected persisted counts — failure/recovery scenario (after pass 2):**

| Count | Value |
|---|---|
| Stored audit events | 3 (error + queued fallback + recovered match decision) |
| Distinct assessments | 1 |
| Assessment error events | 1 |
| Requires-review decision events | 1 |

The original `#match_error` row remains after recovery; recovery adds a separate
`#match_decision` row for the same assessment identity. The original queued
fallback stays pending; recovery does not replace its pack or record an owner choice.

Open the generated HTML under `artifacts/` in a browser. The report lists stored
audit events and distinct assessments separately — event count is not the number
of alerts processed, and “requires review” does not mean the owner was notified.

## notification and owner approval path

The owner decision path keeps the original pending queue row immutable. A separate decision row at
`<assessment_id>#decision` records the first owner choice, while `list` derives
pending/approved/edited/declined status without rewriting the queue. The local
operator CLI is:

```powershell
.\.venv\Scripts\python.exe -m src.runtime.approve --business-id demo-cafe list
.\.venv\Scripts\python.exe -m src.runtime.approve --business-id demo-cafe show <ESCALATION_ID>
.\.venv\Scripts\python.exe -m src.runtime.approve --business-id demo-cafe approve <ESCALATION_ID>
.\.venv\Scripts\python.exe -m src.runtime.approve --business-id demo-cafe decline <ESCALATION_ID>
.\.venv\Scripts\python.exe -m src.runtime.approve --business-id demo-cafe edit <ESCALATION_ID> --pack-file artifacts/edited-pack.json
```

Recording a choice stores owner consent and its audit evidence. It does not send
the draft to customers, remove stock, or execute the action pack. A repeated
choice reports the stored first choice. Edit files are UTF-8 JSON ActionPacks and
are revalidated at both the file and persistence boundaries.

Notification is disabled by default. Explicit `ALLERGUARD_NOTIFICATION_MODE=ses`
uses SES and may use SNS only after a definite SES rejection; `sns` uses the
configured topic directly. A provider message ID means the provider accepted the
request, not that an owner received it in an inbox. Timeouts and ambiguous
transport outcomes are recorded as unknown and are not blindly retried. The
serial read-before-send check does not promise exactly-once external delivery in
the face of crashes or concurrent callers.

The reproducible offline human-loop demonstration uses the real `process_alert`
path, injected matcher/drafter doubles, a simulated provider and one Moto
process:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_human_loop --report artifacts/human-loop.html
```

It reads back 11 events and 3 pending escalations after the initial simulated
notifications, leaves those totals unchanged on replay, records one approve,
one edit and one decline on distinct IDs, then reads back 14 events and zero
pending. The final replay adds no sends or decisions. This proves the offline
orchestration and persistence contract only; it is not live SES, SNS, or inbox
verification.

The complete offline cycle demonstration reads the five replay fixtures through the
alert ledger, commits only after every outcome is persisted, and runs a second poll:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_cycle --owner-choices none --report artifacts/cycle.html --trace artifacts/cycle-trace.json
.\.venv\Scripts\python.exe -m scripts.demo_cycle --owner-choices simulated --report artifacts/cycle-owner.html --trace artifacts/cycle-owner-trace.json
```

The first command records 11 audit events and leaves three pending escalations; the
second also records approve, edit and decline, ending at 14 events and zero pending.
Both runs are offline Moto demonstrations with injected specialist proposals and
simulated provider acceptance. The JSON trace records cycle status, counts and process
identity. A blocked or uncertain cycle never advances the ledger watermark.
A one-time local Windows scheduled invocation (`AllerGuard offline cycle proof`)
ran automatically on 2026-09-12 at 21:14:36 Europe/London and returned result 0.
That proves unattended local offline execution only; it is not production AWS
scheduling.

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
- **Live Bedrock matcher verification** (prior work; five labelled fixtures).
- **Future work:** dashboard, live scheduler, and AgentCore deployment with production
  runtime identity wiring. The
  notification and owner-choice path remains offline-verified only.

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
