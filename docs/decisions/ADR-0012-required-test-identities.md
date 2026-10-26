# ADR-0012: Capture test identities and validate native pytest phases

Status: accepted for trusted local development; isolated evaluation remains planned.

## Problem

ADR-0011 accepted mixed JUnit skips when `allow_skips` was true. A collection
hook could skip a required failing test while leaving a different test passing.
The protected acceptance file stayed unchanged, the command exited zero, and
the requirement was incorrectly reported verified. Aggregate counts cannot
identify which obligations executed.

## Decision

Capture an owner-reviewed manifest before writer execution. Freeze its native
test IDs and exact optional-skip reasons in the round profile. Reject blanket
skip permission, missing/duplicate identities and unauthorized skips. JUnit
requires stable `classname::name` identities. Pytest uses a separate JSON event
adapter recording selected/deselected IDs, collection failures and each
setup/call/teardown outcome. Reject missing/duplicate phases, all-skipped runs,
xfail/xpass and any test failure, including additional tests.

Disable ambient pytest plugin entrypoints and pytest option/plugin environment
variables in the local adapter. Protect configuration, fixture, test and evaluator
source inputs, including configuration paths absent at capture time. The harness
repository enumerates source files rather than hashing cache directories that
differ between an existing checkout and a clean worktree.

## Limits and migration

These are integrity checks in a trusted-development process, not an isolation
boundary. Target code in the same process/account can manipulate collection,
assertions and reports. The isolated evaluator/control-plane receipt phase must
address that threat separately. A passing local run does not prove hostile-code
resistance, software completeness or live-model effectiveness.

Version 1 exit-code profiles remain supported. Structured reports now require
expected identities. Old blanket-skip profiles fail with migration instructions;
recreate their rounds after reviewing manifests. No automatic baseline refresh
occurs during acceptance. CLI and MCP remain optional clients; neither defines
the kinds of target software the core can evaluate.
