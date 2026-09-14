# AllerGuard

**Quiet by design.**

AllerGuard helps small UK food businesses check food recalls against their own stock and ingredients. It brings relevant or uncertain matches to the owner, records why other alerts were handled silently, and brings recall decisions and the daily food-safety diary into one evidence trail.

Built for the **Agents for Humans** hackathon using AWS Strands Agents and Amazon Bedrock.

## Public demo

**[Try AllerGuard](https://allerguard-7se.pages.dev)** · **[View the source code](https://github.com/Ella-Afonso/AllerGuard)**

No account or installation is required.

1. Select **Start fresh demo**, then **Run replay demo**.
2. See five historical recalls assessed: **two handled silently and three sent for review**.
3. Approve, edit, or decline the pending decisions.
4. Open **Audit trail** to inspect the recorded outcomes, including the silent ones.
5. Use **Diary** to file and confirm a daily record, then try the evidence exports.

> The public site is a browser-only simulation using public recalls and a fictional café. It does not run the Python backend, call AWS, or send notifications. The local application and recorded AWS tests below provide separate evidence of the backend implementation.

## Why this project matters

A café owner needs to know whether a recall affects something they sell or use. Reading every alert takes time, while sending every alert to the owner creates noise. Missing batch details or an unfamiliar product name can also make the answer uncertain.

AllerGuard focuses on that decision: explain the connection to the business, keep uncertainty visible, and leave a record of what happened. The daily diary keeps those decisions alongside the owner's opening and closing confirmations.

## What AllerGuard does

| Feature | Purpose |
|---|---|
| Inventory-aware matching | Compare recalls with products, ingredients, allergens, and available batch details. |
| Conservative escalation | Send possible, likely, and confirmed matches for review. Escalate assessment failures too. |
| Action drafts | Prepare a stock-pull instruction, staff note, draft customer notice, and substitution guidance. |
| Owner decisions | Record approve, edit, or decline while retaining the original draft. |
| Daily diary | Prepare a record, link recall evidence, and wait for explicit owner confirmation. |
| Audit and export | Keep silent outcomes, escalations, decisions, and diary records available in CSV and HTML. |
| Repeat-poll protection | Track processed alert versions so later polls do not repeat completed work. |

Recording an approval does not remove stock or send a customer notice. It records the owner's choice; physical actions remain outside this implementation.

## How it works

The Python runtime coordinates retrieval, assessment, persistence, and progress tracking. Strands agents support model-based assessments and drafts. A separate code gate decides whether an assessment can remain silent.

```mermaid
flowchart TD
    A[Public FSA alerts or saved replay fixtures] --> B[Monitoring runtime]
    I[Business inventory] --> C[Matching rules and validated model proposal]
    B --> C
    C --> D{Deterministic safety gate}
    D -->|NO_MATCH| E[Record silent outcome]
    D -->|Relevant, uncertain, or failed assessment| F[Prepare draft and queue for owner]
    F --> G[Owner approves, edits, or declines]
    E --> H[Append-only audit history]
    F --> H
    G --> H
    H --> J[Daily diary and CSV / HTML evidence]
```

The public Pages site illustrates this flow independently. The local FastAPI dashboard calls the Python runtime. The scheduled AWS proof used EventBridge, Lambda, and DynamoDB with fixed assessment proposals and notifications disabled.

## Safety by design

- **Code controls escalation.** Only an assessed `NO_MATCH` can remain silent. The safety gate contains no model call.
- **Models cannot lower the matching floor.** Model proposals are checked against inventory evidence and deterministic rules.
- **Uncertainty stays visible.** An unknown batch is not presented as a confirmed match or proof that stock is safe.
- **Records are added, not rewritten.** Conditional writes preserve the first stored decision and support safe retries. This is application-level append-only behaviour, not a claim of tamper-proof storage.
- **Tests cover missed matches and unnecessary escalation.** The labelled fixture set checks both. Passing it is not a guarantee for every future recall.

## Verification

These are recorded results, with each environment's scope kept explicit.

| Evidence | Result |
|---|---|
| Offline Python suite, 13 September 2026 | **419 passed**, 6 live Bedrock tests deselected, 3 third-party warnings. Ruff and MyPy also passed. |
| Local owner workflow | Five assessments, two silent outcomes, three escalations; approve/edit/decline and replay tested with Moto storage. |
| Diary and export | 15 events before diary confirmation, 16 after confirmation; replay leaves the stored count unchanged. |
| Separate live Bedrock checks | Five labelled matcher fixtures and a separate action-drafter case passed. |
| Scheduled AWS cycle, 13 September 2026 | First unattended run processed five recalls and committed progress. The next run found zero new alerts. |
| AWS stored evidence | Eight audit events, three queued escalations, and six ledger items including the progress marker. |

The AWS cycle ran in `eu-west-2`; its EventBridge rule was disabled after the proof. It used real Lambda and DynamoDB, saved recall fixtures, fixed proposals, and no notifications. It did not test live Bedrock inside that scheduled cycle.

See the [scheduled-cycle guide](infra/cycle/README.md) and [audit storage guide](infra/audit/README.md) for deployment and persistence details.

## Run locally

Use **Python 3.12** and Git. The following commands are for Windows PowerShell. AWS credentials are not needed for the local demo.

```powershell
git clone https://github.com/Ella-Afonso/AllerGuard.git
cd AllerGuard
py -3.12 -m venv .venv
```

Install the application and development dependencies listed in `pyproject.toml`. The development dependencies include Moto, which provides local AWS emulation:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -c "import subprocess, sys, tomllib; p=tomllib.load(open('pyproject.toml','rb'))['project']; subprocess.check_call([sys.executable,'-m','pip','install',*p['dependencies'],*p['optional-dependencies']['dev']])"
```

Start the dashboard from the repository folder:

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_dashboard
```

Open **http://127.0.0.1:8000**, start a demo session, and run the replay. The local application uses the real Python workflow with simulated model proposals and notifications. Its Moto history is lost when the process restarts.

To generate the cycle and diary evidence from the terminal:

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_cycle --owner-choices simulated
.\.venv\Scripts\python.exe -m scripts.demo_diary --date 2026-09-13 --owner-confirmation simulated
```

Reports and traces are written to `artifacts/`. The diary command also creates a CSV export. These commands use fictional business data and do not call AWS.

## Run the checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q -rs -m "not live_bedrock"
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m mypy src
git diff --check
```

The test command excludes paid live Bedrock tests. The 13 September result above is the historical AWS-proof baseline. The 14 September tracker review passed **434 offline tests** (6 live cases deselected), Ruff and MyPy in a fresh Python 3.13.5 environment. The separate public-demo regressions passed **5 Node tests** (`node --test tests/pages_demo.test.cjs`). These are recorded results, not a live CI badge.

## Technology and repository

**Python 3.12 · AWS Strands Agents · Amazon Bedrock · DynamoDB · Lambda · EventBridge · FastAPI · Jinja2 · Pydantic · Moto · pytest · Ruff · MyPy · Cloudflare Pages**

| Path | Contents |
|---|---|
| `src/agents/` | Strands agent prompts and wiring |
| `src/domain/` and `src/safety/` | Data models, matching rules, and deterministic gate |
| `src/tools/` | FSA, storage, audit, and notification integrations |
| `src/runtime/` and `src/api/` | Workflow coordination and dashboard API |
| `web/` | Local dashboard templates and assets |
| `pages-demo/` | Standalone public browser demonstration |
| `fixtures/` and `tests/` | Replay data and automated checks |
| `scripts/` | Local demos and setup utilities |
| `infra/` | AWS templates and operator guides |

See the [detailed architecture](docs/architecture.md), [recording guide](docs/demo-guide.md), and [optional operations and public-demo tests](docs/operations.md).

## Current limitations

Live SES/SNS delivery and inbox receipt remain unverified. The complete product has not been deployed to AgentCore; the earlier AgentCore hello-agent proof was a separate, smaller deployment. Live FSA polling in the scheduled cycle and live supervisor delegation remain outside the recorded proof.

Menu extraction, automatic stock actions, and customer-message execution are not implemented. External delivery is not guaranteed exactly once. The diary and exports support review; they do not certify food-safety compliance.

## Data, attribution, and licence

The demo café and its inventory are fictional. Historical recall fixtures use public information from the **UK Food Standards Agency** and contain public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).

The project code is available under the **MIT Licence**. See [LICENSE](LICENSE).

## AI assistance

Cursor, Claude Code, and OpenAI Codex assisted with planning, implementation, testing, troubleshooting, and documentation. The project uses the open-source libraries listed in `pyproject.toml`; Moto supplies the disclosed offline AWS emulation. AI-assisted changes were checked through code review and automated tests, with live results distinguished from simulations above.
