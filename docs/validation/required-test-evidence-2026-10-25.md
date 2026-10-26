# Required-test evidence validation

Baseline: main `723de3e283157d3beb4adc54613715862df3d3b5` (PR 18).
Scope: PR 0/1 of `docs/plans/universal-core.md`. Other phases remain proposed.

## Baseline and dependencies

The baseline contained 208 Python cases (207 pass, one opt-in live Codex skip)
and 18 extension checks. Initial local verification used a relative PYTHONPATH;
two server tests failed because their subprocesses changed directories. With an
absolute source path, the complete suite passes. This was an invocation problem,
not evidence of an application regression.

`requirements/dev.lock` captures the tested runtime/dev package versions and CI
uses them as constraints. Optional integration SDKs and isolated build tooling
are not locked by that file. This change copies no external source and adds no
new runtime dependency. Existing project licensing remains MIT; dependencies
retain their own metadata/licenses. New SDK/container dependencies need their
own license and provenance inventory before introduction.

## Evidence and limits

Executable regressions in `tests/test_test_evidence.py` reproduce a required
failure, then leave the protected test bytes unchanged while introducing a
collection hook that skips, deselects, removes or xfails that test. Each altered
candidate must fail acceptance. Explicit optional skips remain accepted and
carry their recorded owner reason. Additional tests cover duplicate/missing
phases, unexpected identities, profile migration errors and manifest freezing.

These tests exercise real local pytest subprocesses, not live model sessions.
They do not establish isolation from hostile in-process code. Independent review,
container separation, cross-language coverage and comparative model trials are
subsequent gates in the implementation plan.

Local final results: 228 Python cases passed; only the named optional authenticated
Codex smoke skipped (229 collected). The project verifier ran these through the
native event adapter and passed architecture, layout and lint checks. All 18
extension checks passed, including the real server lifecycle, and TypeScript
compiled. The same project verifier is now the Python CI entrypoint.

One intermediate verifier run correctly rejected a stale captured test ID after
a regression case was renamed, despite pytest passing. The manifest change was
reviewed explicitly; acceptance did not regenerate it. A later run rejected a
one-character lint violation, which was corrected before publication.
