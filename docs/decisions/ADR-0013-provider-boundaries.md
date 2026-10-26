# ADR-0013: Inject verification providers and retain local compatibility

Status: accepted for local verification and provider contract testing.

## Decision

Place transport-neutral candidate, environment, command, evidence and acceptance
values in `kernel`. Define execution, candidate, verifier and evidence-store
Protocols in `ports`. The kernel and ports import only the standard library and
each other; the architecture check rejects vendor and operator-client imports.

`evaluation.runner.verify_with_providers` coordinates injected implementations.
It does not launch subprocesses, invoke Git, parse framework reports or import
concrete adapters. `adapters/execution/local.py` owns POSIX processes, fresh
report collection, bounded output, cancellation and cleanup. The Git adapter
retains the existing source fingerprint. JUnit and native pytest verifiers share
one deterministic acceptance policy. Required capabilities fail before commands
start. Unsupported environments and transport failures block; integrity failures
cannot route a writer back to alter tests until they pass.

The old `evaluation.verify_candidate` API remains an explicit composition shim
in `evaluation/compat.py`. That single file may import adapters. Optional clients
and library callers share `application.build_application`; existing constructors
and CLI/MCP/web behavior remain compatible. Model CLI implementations are loaded
only when that provider is selected.

## Evidence

The local default stores raw structured reports and final verification snapshots
as content-addressed bytes. Blob writes deduplicate without replacing existing
contents; reads verify digest and size. Run receipt files are created once.
Approval and promotion recheck the stored snapshot and its raw-report references.
Existing SQLite round events remain the metadata index; no second event database
or model-based acceptance authority is introduced.

Receipts cover the evaluator's snapshot before application delivery/base metadata
is appended. They are unsigned local integrity records. They do not authenticate
an evaluator against another process running under the same OS account. Log paths
remain existing provider references; this change does not assert that every log,
video or screenshot has already been archived automatically. The binary-store
API can accept those artifacts with an explicit media type and byte budget.

## Source binding and environment provenance

The repository's own profile prepends its worktree `src` before importing the
pytest adapter. A regression reproduces how an editable installed checkout could
otherwise hide candidate-source changes, then verifies the candidate is imported.
The profile protects the extracted evaluator dependencies as well as the tests.

Local environment provenance includes Python runtime facts and declared lockfile
digests. This does not prove the contents of every installed tool or dependency.
The synthetic TypeScript fixture uses its own npm integrity lock, actual compiler,
Node HTTP server and native test reporter. Its correct and intentionally broken
versions are evaluated by the same core policy.

## Remaining boundaries

The simulated remote provider establishes dependency injection, cancellation and
failure contracts; it is not evidence of a deployed remote/container adapter.
The application still manages local Git worktrees and source-bound promotion.
Build/deployment identities, browser journeys, isolated evaluator authority,
direct API agents and live model comparisons remain separate implementation gates.
