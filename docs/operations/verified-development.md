# Verified development rounds

Build and quick rounds now distinguish an agent's stage report from executable
acceptance. A closed actual round requires an owner-supplied project profile,
harness-captured passing checks, unchanged protected acceptance inputs and
unchanged candidate contents through closure. Discovery, review and decision
rounds do not require an application test environment. Dry runs are explicitly
simulated and cannot be promoted.

## Configure a project once

After `icm init`, create `.harness/project.json`. It is not generated or replaced
by an agent. Review its requirements and commands as executable project code:

```json
{
  "schema_version": 2,
  "requirements": [
    {
      "id": "SAVE-001",
      "description": "Authorized saves persist and other tenants cannot overwrite them.",
      "checks": ["api-acceptance"]
    }
  ],
  "checks": [
    {
      "id": "api-acceptance",
      "argv": ["python", "-m", "icm_harness.evaluation.pytest_runner", "--report", ".harness/runtime/api.json", "--", "tests/acceptance"],
      "result_format": "pytest_events",
      "report": ".harness/runtime/api.json",
      "test_manifest": ".harness/api-tests.json",
      "timeout_seconds": 300
    }
  ],
  "protected_paths": ["tests/acceptance", "tests/conftest.py", "conftest.py", "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"],
  "inherit_environment": ["PATH", "HOME", "LANG", "TMPDIR", "TEST_DATABASE_URL"]
}
```

Before creating a round, collect the manifest from reviewed baseline material:

```sh
python scripts/capture_test_manifest.py --output .harness/api-tests.json -- tests/acceptance
```

The capture script creates a new file exclusively; it never refreshes the baseline
automatically. Review and commit it with the acceptance inputs. Use
`--optional native-node-id 'Owner-approved reason'` before `--` for each permitted optional
skip. Alternatively provide `expected_tests` and `optional_skips` inline.
Manifests are expanded and frozen at round creation, never collected from a
writer-modified candidate.

The actual assertions, not the requirement's wording, determine what this
check proves. The owner must ensure meaningful coverage. Code coverage, command
success and a valid JSON report do not establish completeness or correctness.

The profile is captured when a round is created and persists across process
restarts. Editing a worktree copy cannot change the selected commands or criteria.
A missing profile permits planning but blocks actual verification. An invalid
profile rejects round creation. Old rounds lacking a captured profile must be
recreated. Changes to protected acceptance files require a reviewed new round.

## Test environments

Optional `setup`, `reset`, `ready` and `teardown` arrays use the same command
objects as `checks`. The order is setup -> reset -> ready -> checks -> teardown.
Teardown runs after a failed command, timeout or operator cancellation.
Use these hooks for disposable databases, migrations, seeded tenants and health
checks. For example, a setup argv can invoke `docker compose -p <unique-name> up -d`;
the teardown argv should remove that exact disposable environment. Do not point
reset/teardown commands at production data. Services must be managed externally
(for example by Compose); background descendants of a hook process are stopped.

Commands execute directly as argv arrays, without implicit shell expansion.
The local runner currently targets macOS/Linux process-group behavior.
Secrets are not inherited unless their environment variable names are explicitly
listed. This is environment filtering, not a filesystem/network sandbox: commands
run under the operator's OS account. Use a container/VM and separate identities
for hostile agents or confidential workloads. Logs can contain application data;
configure tests to avoid printing secrets. Optional semantic reviews remain
advisory and do not substitute for executable checks.

Each command has a finite timeout (up to one hour); verification has the stage's
total time budget, with up to 30 additional seconds for teardown. Log output is
monitored against a 16 MiB per-command limit. Cancellation kills its process group. Logs,
durations, exit codes and JUnit counts/skips are retained under the round's
verification directory. A `verification.json` artifact is produced by the
harness, not the model. Structured checks reject missing, malformed, empty or
all-skipped reports. Every captured test identity must remain present. Blanket
`allow_skips: true` now rejects the profile, including old captured profiles;
create a reviewed new round with exact optional IDs and reasons. Pytest evidence
requires setup/call/teardown outcomes, with a setup-skip exception only for named
optional tests. Missing, duplicate, deselected, failed, xfail and xpass outcomes
fail acceptance. Additional passing tests are allowed.

The local pytest adapter disables entrypoint plugin autoload and clears
`PYTEST_ADDOPTS`/`PYTEST_PLUGINS`. Explicit `-p` plugins, configuration, conftest
files, fixtures and dependencies still belong to the trusted input set and must
be reviewed/protected. Bytecode writing is disabled by the command runner. Keep
protected directory contents stable across worktrees; prefer explicit source
files and absent configuration paths over directories containing machine-local
cache files. This mode is **trusted development**, not isolated acceptance:
code sharing the evaluator process or OS account can forge reports or restore
changed inputs. Container/control-plane isolation is a separate later phase.

JUnit IDs are `classname::name`; testcase names must be present and unique.
JUnit checks also require a manifest and exact optional IDs, but cannot prove
native pytest execution phases. XML reports must be UTF-8 and cannot contain
DTDs or entity declarations. Use `pytest_events` for pytest. Exit-code-only checks
record command success without inventing test counts.

Tests may write disposable outputs. Git-ignored output is naturally excluded
from candidate identity; `generated_paths` may also name untracked output paths.
Tracked inputs are always fingerprinted, even under a declared generated path.
JUnit output cannot overwrite a tracked input. Check commands that change product
inputs invalidate their own acceptance result. This catches accidental edits;
it does not defeat a malicious process that changes a file and restores it.

## Frontend profiles

Use the same contract for frontend checks, with argv such as
`["npm", "run", "test:components"]`, `["npm", "run", "test:a11y"]`,
`["npm", "run", "test:visual"]` and `["npm", "run", "test:e2e"]`.
Configure those scripts to write fresh JUnit reports to ignored output paths
when counts/skips are required, then select `result_format: "junit"` and the
matching `report` path and a reviewed manifest of `classname::name` IDs. Playwright journeys should exercise the connected app;
Storybook tests alone do not establish backend integration. Keep Figma document
references and approved states in the planner's context. No Figma, browser or
Storybook dependency is required for projects that do not need them.

## Repair and promotion

The writer gets the original objective, captured requirements, prior stage
artifacts and latest command failure. Failure signals widen context through the
existing settings policy. Implementation failures return to the writer within
the round's transition limit. Environment failures block instead of repeatedly
asking the writer to change code. In quick mode a failed check stops the round;
use build mode for an automatic writer/tester repair cycle.

Close stages cannot modify product inputs. Verification records candidate contents,
profile digest and destination revision. Approval records that exact verification
run. Promotion checks them again and rejects any intervening candidate change or
destination movement. Recreate the round on the new base when either changes.
Promotion excludes generated untracked outputs and requires the destination to be
an ancestor of the verified commit, preventing an untested combined merge tree.
These checks serialize harness promotions, not arbitrary external filesystem/Git
writers; use an isolated workspace to eliminate that concurrent-writer threat.

The repository's own `.harness/project.json` provides executable Python and
architecture checks. Install the dev dependencies before using it. It explicitly
permits the optional live-model smoke to be skipped; it does not claim a live
provider was exercised. Extension checks remain a separate CI job.

## Provider-neutral library use

`from icm_harness.application import build_application` creates the existing
application without importing operator CLI, MCP or web modules. A supplied
`StageAgent` can run without either model CLI adapter. Existing entrypoints stay
available as optional clients.

Use `VerificationProviders(execution, candidate, verifiers, evidence=None)` from
`icm_harness.ports` to supply explicit implementations. Pass the bundle as
`providers=` to `build_application` or `verify_with_providers`. The legacy
`verify_candidate` composes local defaults when no bundle is supplied. The
application still requires its local Git workspace/promotion infrastructure;
provider-neutral verification does not yet make the entire application remote.

Profiles can specify `required_capabilities`, for example `["process",
"filesystem"]`. An unavailable capability blocks before setup/check commands.
The local provider reports POSIX process support and trusted-development mode.
It records Python runtime facts and declared lockfile digests, not a complete
attestation of installed dependencies. Cancellation invokes the provider and
always attempts cleanup. A cleanup failure invalidates acceptance.

The default local evidence store lives under the verification directory's
`store/`. It stores raw reports and final snapshots by SHA-256, checks them on
read, and creates each run receipt once. Approval checks the receipt and raw
report blobs again. `FilesystemEvidenceStore.put_blob(bytes, media_type)` also
supports explicit binary artifacts, with a default 32 MiB blob limit. Existing
round event records index the result. These are local integrity receipts; an
isolated evaluator and external authority remain separate requirements.

For Python projects with a `src` layout, explicitly select the candidate source
before importing its test framework/adapter. The repository's profile does this
with `sys.path.insert(0, 'src')` in its captured argv. An editable installation
pointing to another checkout is insufficient evidence about the candidate.

## Cross-language acceptance fixture

Run the synthetic TypeScript target without a live model or service account:

```sh
npm ci --ignore-scripts --prefix fixtures/typescript_api
python scripts/verify_typescript_fixture.py
```

The script creates a temporary Git candidate, compiles its TypeScript, runs three
native tests against a real local HTTP server, and requires acceptance. It then
changes an unauthorized response from 401 to 200, recompiles, and requires
rejection. Raw reports and receipts remain under
`.harness/runtime/typescript-validation/`. CI runs this on Node 20. Test cases and
tokens are synthetic. This fixture establishes API test integration; visual
browser checks and build/deployment-bound delivery remain later gates.

## Built outputs and browser evidence

Add `artifact_paths` to bind acceptance to explicit built files:

```json
{
  "generated_paths": ["dist"],
  "artifact_paths": ["dist/application.zip"]
}
```

The local provider deletes declared untracked output files before environment
hooks. Have `setup`, `reset` or `ready` produce them. A stale file cannot stand in
for a successful build. Tracked files, symlink outputs, protected-input/report
collisions and paths outside generated/runtime areas are refused. Every declared
file must exist before checks, stay unchanged through cleanup, and match again
at approval/promotion. Each file is limited to 32 MiB; use explicit packaged
artifacts rather than directory globs. Source promotion records the tested
artifact digest but does not automatically deploy or copy those files.

A check's optional `attachments` field declares required binary evidence:

```json
{
  "attachments": {
    ".harness/runtime/browser/desktop.png": "image/png",
    ".harness/runtime/browser/desktop.zip": "application/zip"
  }
}
```

Declared attachments are cleared before that command and stored by content hash
afterward, including when an ordinary test failure exits nonzero. A missing
required attachment cannot produce passing acceptance. Media types are declared
metadata, not an independent determination of file format or evidentiary adequacy.
Approval rechecks stored attachment bytes. Injected execution providers must
advertise `fresh-artifacts` when using these fresh-output contracts.

The TypeScript fixture now needs its pinned Chromium installation:

```sh
npm ci --ignore-scripts --prefix fixtures/typescript_api
cd fixtures/typescript_api
npx playwright install --with-deps --only-shell chromium
cd ../..
python scripts/verify_typescript_fixture.py
```

The experiment checks three API tests and two browser journeys (desktop 1280x800,
mobile 390x844). It also requires independent rejection of API authorization and
browser-only regressions. Screenshots/traces and built bytes are retained in the
verification store; CI uploads the synthetic evidence. Example passing screenshots
are copied to `.harness/runtime/browser-qa/`. No client data or live model is used.
