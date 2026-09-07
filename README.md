# AllerGuard

AllerGuard is an autonomous agent system being developed for small UK food businesses. It is designed to monitor Food Standards Agency (FSA) recall alerts against a business’s inventory, maintain a daily safety record, and surface decisions requiring human review.

## Status

Foundation stage.

- The project folder scaffold is in place.
- Amazon Bedrock inference has been tested successfully from the AWS console and local PowerShell terminal.
- The agent workflow, dashboard, and AWS deployment are not implemented yet.

A successful Bedrock request confirms model access. It does not mean the AllerGuard application is complete.

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
$env:BEDROCK_MODEL_ID = 'eu.anthropic.claude-sonnet-4-5-20250929-v1:0'
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
python -m ruff check src
python -m ruff format --check src
python -m mypy src
```

These checks examine code style and typing. Passing them on a scaffold does not verify application behaviour.

Once behavioural tests have been implemented, run:

```powershell
python -m pytest
```

An empty test directory does not count as a passing test suite.

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

These directories currently represent the intended structure. Their presence does not imply that their functionality has been implemented.

## Design requirements

The implementation must satisfy these requirements:

- No genuinely relevant recall in the labelled test set may be classified as `NO_MATCH`.
- Uncertain matches must be escalated for human review.
- The escalation gate must use deterministic code and contain no model calls.
- Every processing outcome, including errors, must produce an append-only audit record.
- External side effects must be implemented through tools.
- Replay and live monitoring must share the same processing code path.
- Demonstrations must use fictional, synthetic, or public data.

These are acceptance criteria for the planned implementation, not claims of functionality already delivered.

## Tools and AI assistance

Claude Code was used for planning, setup guidance, troubleshooting, and documentation assistance. Cursor Agent was used to assist with project setup and documentation updates.

The planned application stack includes:

- Python 3.12 with venv and pip
- AWS Strands Agents SDK and Strands Agents Tools
- Amazon Bedrock
- Boto3 with its CRT extra
- Pydantic
- pytest, Ruff, and mypy

This disclosure will be updated as implementation progresses and additional tools or pre-existing code are used.

## Licence

MIT. The `LICENSE` file has not been added to the repository yet; it is tracked as outstanding foundation work.