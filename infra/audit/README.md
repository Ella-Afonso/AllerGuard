# Audit table — operator guide

The audit integration adds a deterministic gate and a durable audit boundary. It does **not**
deploy the supervisor, send notifications, record approvals, advance the poll
watermark, or perform any human action on behalf of the owner.

## Verification status

| Environment | Status |
|---|---|
| **Offline (Moto)** | Verified. `tests/test_audit.py` and `tests/test_process_alert.py` exercise conditional writes, idempotent reuse, error/recovery coexistence, and audit outage propagation against an in-memory DynamoDB mock. No real AWS credentials required. |
| **Live AWS (audit tools only)** | Verified (2026-09-10). Real audit table configured via `ensure_audit_table()`; dedicated assumed-role runtime access verified; **synthetic** append/read, duplicate protection, separate-process persistence, and error/recovery row preservation exercised through `src/tools/audit.py` only. |

Use Moto for development and CI. Live verification used **real DynamoDB API
operations** under a scoped assumed-role identity — not IAM policy simulation
alone. (Policy simulation may be used during IAM setup to sanity-check attached
permissions; it does not substitute for live read/write checks.)

### Verified live scope (do not overclaim)

| Verified | Not verified |
|---|---|
| Table provisioned and reachable | Live `process_alert` → DynamoDB end-to-end |
| Runtime IAM attached to a dedicated verification role | Live Bedrock end-to-end run |
| Synthetic append/read via audit tools | AgentCore production deployment |
| Duplicate `PutItem` protection (`created=false` on reuse) | Supervisor, notification, approval, watermark |
| Separate-process read-back of persisted rows | Tamper-proof / WORM storage |

Synthetic verification rows were **intentionally retained** in the live table for
inspection. Local verification inputs and results stay in gitignored `artifacts/`
and are not published here.

## Table design

| Property | Value |
|---|---|
| **Table name (default)** | `allerguard-audit` |
| **Region (default)** | `eu-west-2` |
| **Partition key** | `business_id` (String) |
| **Sort key** | `entry_id` (String) |
| **Billing** | `PAY_PER_REQUEST` (on-demand) |
| **Deletion protection** | Enabled when the table is **created** by `ensure_audit_table` |
| **TTL** | None |

### Configuration

| Setting | Environment variable | Default |
|---|---|---|
| Table name | `ALLERGUARD_DYNAMODB_TABLE_AUDIT` | `allerguard-audit` |
| AWS region | `AWS_REGION` | `eu-west-2` |

Region is read by `Settings.from_environment()` and passed to boto3 clients in
`src/tools/audit.py`. The application does not hard-code a region outside
`src/config.py` defaults.

## Permissions — operator vs runtime

These are **different identities** with different needs.

### Operator (setup / provisioning)

Used when an human or deployment pipeline runs `ensure_audit_table()` once to
create or validate the table. Required API actions:

- `dynamodb:CreateTable`
- `dynamodb:DescribeTable`

`ensure_audit_table(settings=None)` reads configuration from the environment
(via `Settings.from_environment()` when `settings` is omitted), creates the table
only if missing, waits until it exists, and rejects an incompatible existing
schema. It does **not** modify deletion protection or policies on a table that
already exists.

### Runtime (application reads and appends)

The running matcher/gate/audit seam calls only:

| Allowed at runtime | Function |
|---|---|
| `GetItem` | `get_audit_entry(business_id, entry_id, settings=None)` |
| `Query` | `list_audit_entries(business_id, settings=None, *, page_size=100)` |
| `PutItem` | `append_audit_entry(entry, settings=None)` |

Runtime does **not** call `CreateTable`, `DescribeTable`, `Scan`, `UpdateItem`,
`DeleteItem`, `BatchWriteItem`, or PartiQL mutation. There are no update or delete
functions in `src/tools/audit.py`.

See `runtime-policy.example.json` for a template runtime IAM policy. Substitute
your account, region, and table name placeholders before attach. Attach it to the
runtime identity only — not to the operator identity used for table creation.

**IAM policy simulation** (e.g. `simulate-principal-policy`) confirms that a
principal *would* be allowed or denied an action on paper. **Live verification**
means calling `append_audit_entry`, `get_audit_entry`, and `list_audit_entries`
against a real table under the scoped runtime role. Both are useful; only the
latter proves persistence behaviour.

### Prohibited application operations

The codebase exposes **no** API for:

- `UpdateItem`
- `DeleteItem`
- `BatchWriteItem`
- `PartiQLUpdate` / `PartiQLDelete`

Tests assert `update_audit_entry` and `delete_audit_entry` do not exist.

## Append-only — what is and is not guaranteed

**Application-enforced append-only (not WORM):**

- Every write uses a conditional `PutItem`:
  `attribute_not_exists(business_id) AND attribute_not_exists(entry_id)`.
- A duplicate key reads back the first stored row and returns it as reused; identity
  fields must match or `AuditPersistenceError` is raised. Output fields (timestamp,
  reason prose) on a retry do **not** overwrite the first event.
- **Deletion protection** applies to the **table**, not to individual items. It
  prevents accidental table deletion; it does not make rows immutable.
- A principal with unrestricted `PutItem` can still issue an **unconditional**
  overwrite outside this application. Denying `UpdateItem`/`DeleteItem` in IAM
  blocks those APIs but does **not** by itself prevent an unconditional `PutItem`
  overwrite. Administrators can also change policies. Do not describe this store as
  tamper-proof or compliance-grade WORM storage.

## Idempotency and event keys

Assessment identity is a SHA-256 hash (`assessment_id`) over canonical JSON of:
alert content/version, inventory snapshot, model ID, proposal mode, and policy
version (`ASSESSMENT_POLICY_VERSION` in `src/domain/audit_identity.py`). Execution
time and model prose are excluded.

| Event | Sort key pattern |
|---|---|
| Successful assessment | `{assessment_id}#match_decision` |
| Assessment failure | `{assessment_id}#match_error` |

Behaviour:

- Unchanged inputs → same `assessment_id` → `process_alert` reads the prior
  `#match_decision` row and returns it **without calling the model again**.
- Changed alert version, inventory, model, mode, or policy → new
  `assessment_id` → new row.
- A failed assessment writes `#match_error` (tier null, decision ESCALATE). A later
  successful retry appends `#match_decision` for the same assessment; the error row
  is preserved. Repeated identical failures deduplicate on the error key.
- Audit idempotency is a **decision ledger**, not a log of every network attempt,
  and does **not** guarantee exactly-once notification (future queue work).

## Error handling

If DynamoDB is unavailable or a read/write fails, the application raises
`AuditPersistenceError`. Processing **cannot** return a successful receipt without
a durable row — `process_alert` propagates the error; it does not swallow storage
failures inside the matcher-error boundary.

- Read failure before assessment → assessor/model is not called.
- Write failure after assessment → no `ProcessedAlert` is returned; the caller
  must surface the outage, continue other alerts, and withhold watermark advance.

`AuditPersistenceError` carries `decision = ESCALATE` as a hint for upstream
handling; it is not proof that a human was notified.

## Operator setup (live AWS)

From the repository root, using an authenticated operator profile:

```powershell
$env:AWS_PROFILE = 'allerguard-dev'
$env:AWS_REGION = 'eu-west-2'
$env:ALLERGUARD_DYNAMODB_TABLE_AUDIT = 'allerguard-audit'
.\.venv\Scripts\python.exe -c "from src.tools.audit import ensure_audit_table; ensure_audit_table()"
```

Signature: `ensure_audit_table(settings: Settings | None = None) -> None`

If the table already exists, `ensure_audit_table()` validates the schema and
returns without recreating it. Confirm **ACTIVE** status and the partition/sort
keys in the console after first provision.

## Inspecting rows (AWS Console)

1. Open **DynamoDB → Tables → `allerguard-audit`** (or your configured name).
2. **Explore table items → Query** (not Scan).
3. Partition key: `business_id = demo-cafe` (fictional demo business).
4. Run.

Sort keys are `{assessment_hash}#match_decision` or `#match_error`. Timestamps
are stored as attributes; `list_audit_entries` orders by `(timestamp, entry_id)`.

## Offline demonstration (Moto — verified)

No AWS calls; uses injected proposals and ephemeral in-memory storage:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_gate_audit
.\.venv\Scripts\python.exe -m scripts.demo_gate_audit --scenario full --report artifacts/audit-full.html
.\.venv\Scripts\python.exe -m scripts.demo_gate_audit --scenario failure --repeat 3 --report artifacts/audit-recovery.html
```

Records disappear when the process exits. The HTML report is a read-only snapshot
from `list_audit_entries`; it is not an approval interface.

## Live demonstration (Bedrock + DynamoDB — not verified end-to-end)

The `--live` demo path invokes real Bedrock and writes persistent DynamoDB rows via
the demo script. It is **not** the same as the verified audit-tool checks
above: Live Bedrock end-to-end has **not** been run. Requires AWS credits;
create the table with `ensure_audit_table()` first, or pass `--create-table`:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_gate_audit --live --scenario headline --report artifacts/audit-live.html
```

Use a scoped runtime role for writes in shared accounts; do not run against
production identities without review.

## Synthetic data only

All demo and test data is fictional or public (OGL-licensed FSA fixtures). The
demo business **The Walnut & Whisk Café** is synthetic. No real personal, health,
or business data belongs in this table.

## What the audit verification does not include

- Live `process_alert` on real DynamoDB (verified offline + audit tools only)
- Live Bedrock end-to-end verification
- AgentCore production deployment of the audit runtime role
- Approval queue or owner decisions
- SES/SNS notification or delivery guarantees
- Supervisor orchestration or watermark commits
- Tamper-proof / WORM compliance claims (append-only is application-enforced)
