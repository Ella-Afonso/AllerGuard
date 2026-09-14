# Optional operations and reproducible checks

The free replay demo needs no live AWS connection. These optional capabilities are separate from the public Cloudflare Pages simulation.

## Initial live FSA poll

`ALLERGUARD_FSA_INITIAL_SINCE` supplies an explicit timezone-aware starting timestamp only when live mode has no stored watermark. Choose the earliest date required for the intended coverage; there is no automatic “start now” default that might silently omit earlier recalls.

Example configuration, not an instruction to start live processing:

```powershell
$env:ALLERGUARD_FSA_INITIAL_SINCE = "2026-09-01T00:00:00Z"
```

A stored watermark always takes precedence. Replay is unchanged. The initial timestamp is only a retrieval boundary: it does not pre-write a watermark or mark alerts processed. Normal successful cycle completion remains the commit boundary. An unset initial value with no live watermark still fails explicitly. This configuration path is tested offline; live first-poll execution has not been verified.

## Archive a reviewed public or synthetic file

The storage helper uploads one explicitly selected file to an existing bucket. It does not create buckets or alter access policies. AWS credentials must already be available in the terminal, and the caller needs scoped S3 PutObject/GetObject permissions for the chosen prefix. Use a private bucket approved for the project.

```powershell
python -m scripts.archive_file fixtures/nomatch_1.json --bucket YOUR_EXISTING_BUCKET --prefix public-fixtures --public-or-synthetic
```

Replace the bucket placeholder before using this command. It performs a real upload. Only upload reviewed public recall fixtures or synthetic evidence, never credentials or private documents.

The helper limits files to 10 MiB, encrypts uploads with S3 AES256, uses a SHA-256 content-addressed key and conditional creation, and returns a JSON receipt. Repeating the same upload verifies existing bytes before reuse. Save the receipt to use `read_stored_file(StoredFile(...))` for verified retrieval. A same-name file with different contents receives a different key. This is not S3 Object Lock and is not the append-only audit ledger.

Tests cover rejection, duplicate verification, corruption and bounds with fake S3 responses. No live bucket mirror or live upload is claimed by those tests.

## Regenerate and test the public demo

```powershell
python -m scripts.build_pages_data
python -m pytest tests/test_pages_snapshot.py -q
node --test tests/pages_demo.test.cjs
```

The generator runs the canonical fixture assessments and draft validation with injected proposals, then writes `pages-demo/data.js`. It does not call AWS. Commit this snapshot with the app when publishing. The parity test catches stale fixture data; Node tests cover replay, owner choices, diary confirmation, CSV payloads and prohibited inline handlers.

Before publishing, test in a browser with the `_headers` security policy applied. A plain Python static server does not apply Cloudflare's header file. Check approve, edit, decline, repeated replay, diary confirmation, both downloads and a narrow screen.

## Windows test-environment recovery

If `.venv` refers to a Python installation that no longer exists, create a separate environment using an installed supported Python (3.12 or 3.13), then install the dependencies from `pyproject.toml` as described in the root README. Do not treat a launcher error as an application-test failure.

A later audit found `.venv` healthy again on Python 3.12.10. `.local/tracker-venv` (Python 3.13.5) remains a fallback. If pytest cannot access its temporary directory, choose a fresh writable `--basetemp`; retain the original error when reporting results.
