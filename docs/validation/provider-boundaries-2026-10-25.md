# Provider boundaries and cross-language verification

Base: main `abac77996963309ff9a00f08ccfbe179ece7e565` (PR 19).
Scope: provider extraction from PR 2, binary evidence, and an initial API fixture
from PR 4 of the universal-core plan. This does not complete the rollout.

## Implemented and exercised

- Provider-neutral verification with explicit execution/candidate/verifier/store
  contracts; preserved local API/client compatibility and existing approval checks.
- Real local process lifecycle, limits and cancellation; simulated remote locator
  execution with host subprocess calls forbidden in the contract test.
- Unsupported capabilities, transport errors and cleanup errors block acceptance.
  Integrity failures cannot initiate a writer loop that changes acceptance inputs.
- A real library round closes with operator CLI/MCP/web and both CLI model-provider
  modules unavailable. This uses a deterministic test agent, not a live model.
- Content-addressed binary storage, deduplication, atomic create-only run receipts,
  tamper detection and approval refusal after snapshot or raw-report corruption.
- Candidate-source binding: the new regression failed against the old self-test
  argv because it imported the installed checkout. It passed after the profile
  selected the candidate's `src` before importing the evaluator.
- A real compiled TypeScript HTTP API passes three native tests. A separately
  evaluated candidate returning 200 instead of 401 for unauthorized writes is
  rejected. Both runs preserve raw JUnit and verification snapshots.

Local Python validation: 252 passed, one named optional authenticated Codex smoke
skipped (253 collected). Architecture, layout, Ruff and compilation passed.
All 18 extension tests, TypeScript compilation and VSIX packaging passed.
A wheel built successfully and its provider/application modules imported from a
fresh isolated installation. CI results are recorded with the pull request.

## Dependencies, models and data

Python runtime/dev libraries use the existing `requirements/dev.lock`; no new
Python package, vendor SDK or external repository source is introduced.
The TypeScript fixture has an npm integrity lock with TypeScript 5.9.3
(Apache-2.0), @types/node 20.19.43 (MIT), and undici-types 6.21.0 (MIT), matching
already-used extension dependency versions. No dependency implementation was
copied into the repository. Fixture source, inputs, token and binary samples are
synthetic. No client documents, training dataset or live model is used.

Local execution used Node 24.22.1; the new CI target explicitly uses Node 20.
The temporary target installs dependencies from its pinned fixture lock in CI;
the local regression script links the already-installed fixture dependencies.
Environment records describe the harness Python runtime and declared lockfile
digests. They do not attest every installed binary or dependency's content.

## Remaining verification limits

No Docker executable is available in this workspace. No live OpenAI/Anthropic API
credentials are configured for model trials. The simulated remote provider does
not substantiate a real remote/container execution claim. Local receipts share
the operator's OS identity and are unsigned; they cannot establish authority
against a hostile process with that identity. Existing promotion delivers Git
source. Build/deployment identity, browser journeys, isolated evaluator authority,
direct API agent tools, comparative model trials and independent review remain
separate gates. No broad model-performance claim follows from these tests.
