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
  "schema_version": 1,
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
      "argv": ["python", "-m", "pytest", "tests/acceptance", "--junitxml=.harness/runtime/api.xml"],
      "result_format": "junit",
      "report": ".harness/runtime/api.xml",
      "timeout_seconds": 300
    }
  ],
  "protected_paths": ["tests/acceptance"],
  "inherit_environment": ["PATH", "HOME", "LANG", "TMPDIR", "TEST_DATABASE_URL"]
}
```

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
harness, not the model. JUnit checks reject missing, malformed, empty or all-skipped
reports. Mixed skipped tests require explicit `allow_skips: true`; skipped cases
remain visible and are not represented as passed cases. Exit-code-only checks
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
matching `report` path. Playwright journeys should exercise the connected app;
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
