# ICM universal core: implementation plan

Status: implementation underway. The required-test identity and local evaluator
integrity phase is implemented; provider extraction, isolation, cross-language
adapters, API providers and comparative trials below remain proposed.
Baseline: sps18209/ICM-HARNESS, main 723de3e283157d3beb4adc54613715862df3d3b5.
Basis: ICM-RRA-UNIVERSAL-CORE-001 and the demonstrated required-test skip bypass.

## 1. Outcome and first release scope

Develop one orchestration and evidence engine that can work with different
software languages and environments through explicit contracts. Keep CLI, MCP,
the existing console and VS Code extension as optional clients. Do not conflate
the optional operator CLI with a model provider that invokes Codex/Claude CLI.

First supported combinations: local and container execution; Python and
TypeScript/JavaScript target projects; Python acceptance checks and browser/API
journeys; captured source and container/build identities. Existing clients remain
compatible. Desktop/mobile/device/GPU execution gets named extension points but
is not claimed supported until a corresponding adapter passes acceptance tests.

No new vector database, graph database, workflow service, training pipeline,
plugin marketplace or frontend rewrite is required for the initial release.

## 2. Languages and dependency choices

| Surface | Choice | Reason |
| --- | --- | --- |
| Engine and first-party adapters | Existing Python >=3.11; retain CI 3.11/3.12/3.13 | Preserve working code and asynchronous runtime |
| Contracts | Python dataclasses/enums/typing.Protocol; versioned JSON Schema at boundaries | Separate domain logic from transport serialization |
| Existing operator console | Existing HTML/CSS/JavaScript | No migration needed to make the engine generic |
| VS Code extension | Existing TypeScript | Preserve its API client and integration tests |
| Initial target fixtures | Python and TypeScript/JavaScript | Demonstrate host language differs from target language |
| Target-native tools | pytest; npm scripts and Playwright Test for TS targets | Run a project's native checks instead of translating its code |
| State and evidence metadata | SQLite plus append-only events and content-addressed files | Local, inspectable baseline without a server dependency |
| Profiles, manifests, datasets | Versioned JSON/JSONL; TOML configuration | Explicit parsing and reproducibility |

Runtime libraries: keep AnyIO; stdlib dataclasses, typing, enum, json, tomllib,
sqlite3, hashlib, pathlib, importlib.metadata and statistics. Add jsonschema for
external contract validation and defusedxml for the JUnit adapter. Optional extras:
openai, anthropic, swe-rex and playwright. Dev/evaluation extras: pytest, Ruff,
Hypothesis, and datasets only for importing selected public benchmark tasks.

Resolve exact compatible dependency versions during PR 0, commit a lockfile,
and record the lock digest and container image digest for every measured run.
Do not invent version pins in this planning document. Use explicit provider
registration initially; defer Pluggy until third-party hook composition is needed.

## 3. Target folder structure

This is the eventual shape, not an instruction to move all files at once.
Keep current import aliases while moving concrete implementations behind ports.

```text
ICM-HARNESS/
  pyproject.toml
  uv.lock
  src/icm_harness/
    kernel/
      contracts.py
      verification.py
      evidence.py
      identity.py
      capabilities.py
      lifecycle.py
      errors.py
    ports/
      agent.py
      execution.py
      candidate.py
      verifier.py
      evidence_store.py
      review.py
    application/
      service.py
      acceptance.py
      verification.py
      handoffs.py
      repair.py
      promotion.py
      bootstrap.py
    policies/
      acceptance.py
      evaluator_access.py
      model_selection.py
      disclosure.py
    adapters/
      agents/
        codex_cli.py
        claude_cli.py
        openai_api.py
        anthropic_api.py
        deterministic.py
      execution/
        local.py
        swerex_container.py
      candidates/
        git_source.py
        directory.py
        container_image.py
        deployment.py
      verifiers/
        process.py
        pytest.py
        playwright.py
        junit.py
        json_events.py
      storage/
        sqlite.py
        filesystem.py
    evaluator/
      service.py
      pytest_plugin.py
      manifest.py
      attestation.py
      image/
        Dockerfile
        requirements.lock
    interfaces/
      cli/
      mcp/
      web/
    experiments/
      runner.py
      metrics.py
      controls.py
    context/
    routing/
    modes/
    observability/
    integrations/
  schemas/
    project-v2.schema.json
    test-manifest-v1.schema.json
    candidate-v1.schema.json
    evidence-v1.schema.json
    evaluator-receipt-v1.schema.json
    review-v1.schema.json
  profiles/
    python-local.json
    typescript-container.json
    web-browser.json
  benchmarks/
    tasks/
    manifests/
    splits/
    expected-outcomes/
  tests/
    unit/
    contracts/
    acceptance/
    adversarial/
    integration/
    fixtures/
      python_api/
      typescript_api/
      web_app/
      broken_candidates/
  docs/
    architecture/
    decisions/
    operations/
    validation/
  extension/
```

Hidden/held-out evaluation material must live outside a writer's mount and
credentials. A directory named benchmarks or evaluator inside the same repository
is an organizational boundary, not an access-control boundary. Public fixtures
can remain in the repo; isolated acceptance bundles are exported separately.

Dependency rule: kernel -> stdlib only; ports -> kernel; policies -> kernel/ports;
application -> kernel/ports/policies; adapters -> ports/kernel/vendor libraries;
bootstrap imports concrete adapters and wires them into application services;
interfaces invoke application use cases. Prevent core imports of interfaces or
vendor adapters in the architecture validator. No cyclic dependency is allowed.

## 4. Contracts and function inventory

All names below are proposed unless identified as existing upstream calls.

### Domain objects

| Object | Required information |
| --- | --- |
| RequirementSpec | ID, observable behavior, applicability, check IDs, acceptance rule, expected evidence strength |
| VerificationPlan | Profile version/hash, requirements, checks, expected manifest, explicit optional IDs, evaluator identity and budgets |
| TestManifest | Canonical test IDs, required IDs, optional IDs, config/plugin/fixture hashes, collection baseline identity |
| CandidateRef | Source digest, optional built artifact digest, deployment identity and configuration digest |
| EnvironmentRef | Provider, OS/architecture, toolchain/lock/image digests, capabilities, isolation mode |
| CheckObservation | Native check/test ID, phase, outcome, timestamps, provenance and raw evidence references |
| EvaluationEvidence | Candidate/environment/evaluator/plan identities, observations, integrity findings, limitations and receipt |
| AcceptanceDecision | Accepted/rejected/blocked/inconclusive, reason codes, requirement results and supporting evidence hashes |
| ReviewRecord | Reviewer identity, reviewed candidate, findings/disposition and method |

Command completion, observed behavior and interpreted adequacy are distinct
evidence kinds. Failure, skip, expected-failure, unexpected-pass, missing,
deselected, unsupported and infrastructure failure remain distinct outcomes.
Parameters and retries need stable framework-native identities, not display names.

### Application services

| Module | Function | Responsibility |
| --- | --- | --- |
| application/acceptance.py | capture_plan(profile, objective, manifest) -> VerificationPlan | Validate and persist the pre-write contract |
| application/acceptance.py | decide_acceptance(plan, evidence) -> AcceptanceDecision | Deterministic decision; no model call |
| application/verification.py | verify_candidate(plan, candidate, environment, cancel) -> EvaluationEvidence | Coordinate injected providers and evidence collection |
| application/handoffs.py | build_handoff(round_id, stage, evidence_refs) -> StageContext | Supply authoritative requirements and relevant prior evidence |
| application/repair.py | classify_failure(evidence) -> FailureRoute | Route implementation, plan, environment, integrity or unresolved failure |
| application/promotion.py | approve_candidate(actor, candidate, evidence_hash) -> Approval | Record authenticated, candidate-bound authority |
| application/promotion.py | promote_candidate(candidate, approval, destination) -> PromotionRecord | Recheck evidence and identities at delivery |
| application/bootstrap.py | build_application(config, provider_registry) -> HarnessApplication | Select implementations without importing them into the core |

Integrity failures must not simply ask the writer to modify tests until green.
They invalidate acceptance and produce a reviewable finding. Environment failures
must not penalize the writer's coding-quality metric.

### Provider ports

| Port | Methods | First implementations |
| --- | --- | --- |
| AgentProvider | run_stage(invocation, tools, cancellation) -> StageResult | Existing CLI adapters; then direct API adapters |
| ExecutionProvider | capabilities(); prepare(spec); execute(handle, command); cancel(handle); collect(handle); close(handle) | Existing local runner; SWE-ReX container wrapper |
| CandidateProvider | capture(locator); fingerprint(ref); assert_unchanged(ref); resolve_artifact(ref) | Git source; then image/build/deployment adapters |
| VerifierProvider | collect(plan, candidate, environment); evaluate(plan, candidate, environment) | Pytest with trusted events; process and browser adapters |
| EvidenceStore | put_blob(bytes); append_event(event); get_blob(hash); seal_run(manifest) | Filesystem content-addressed blobs plus SQLite metadata |
| ReviewProvider | review(candidate, evidence) -> ReviewRecord | Recorded human review; optional model assistance marked advisory |

File/resource locators must not be assumed local pathlib.Path objects in domain
contracts. Adapters resolve local paths, URIs, image digests and deployment IDs.
Keep textual summaries separate from binary artifacts such as videos, screenshots,
traces and packaged applications.

## 5. Required-test execution and evaluator integrity

This is PR 1 and precedes the generalization refactor.

Functions in evaluator/manifest.py and application/acceptance.py:

```python
capture_expected_tests(trusted_collection) -> TestManifest
compare_collection(manifest, observed_ids) -> CollectionVerdict
validate_outcomes(manifest, events, policy) -> OutcomeVerdict
assert_evaluator_inputs(expected_hashes, actual_hashes) -> IntegrityVerdict
verify_evaluator_receipt(receipt, expected_identity) -> ReceiptVerdict
```

Do not replace allow_skips=True with a minimum total count: the wrong tests could
still run. Every required ID must be collected and produce the expected execution
phases. Optional skips need an exact ID and recorded reason. Reject missing IDs,
duplicate/ambiguous identities, deselected required tests, unexpected skips,
collection errors, phase omissions and unresolved expected-failure outcomes.
New tests may be added; required tests cannot be replaced by unrelated tests.

The manifest must be captured from reviewed acceptance material in a trusted
baseline environment before writer changes. Collecting from the already-modified
candidate and declaring that collection authoritative would preserve the bypass.
Framework-specific adapters handle stable parameter IDs and multi-phase reports.
JUnit alone is insufficient for reliable pytest collection and phase identities.

Use a trusted pytest plugin with pytest_collection_finish,
pytest_deselected and pytest_runtest_logreport. Invoke pytest.main in the evaluator
process with explicit configuration/plugin selection; clear PYTEST_ADDOPTS and
PYTEST_PLUGINS unless explicitly approved and disable entrypoint autoload.
Pin fixture/conftest/plugin/configuration digests. Disabling plugin autoload does
not disable conftest loading or defend against hostile test code in-process.

Two explicitly labeled execution modes:

1. Trusted-development mode: local process with integrity comparisons, suitable for
   accidental changes and ordinary debugging. No hostile-process guarantee.
2. Isolated-acceptance mode: separate evaluator image/process identity; read-only
   acceptance bundle, writer cannot mount evaluator state or receive evaluator
   credentials/Docker socket; restricted network and separate output channel.
   Prefer external black-box assertions against a target process for hostile code.

The control plane generates the authoritative receipt from execution it owns.
An agent-written JUnit file or a signature generated inside an agent-controlled
process cannot establish evaluator authenticity. Keep receipt verification keys
outside the writer; add signing only when the trust boundary needs it.

## 6. Actual libraries and calls

| Library | Calls/mechanisms | Where used |
| --- | --- | --- |
| stdlib typing/dataclasses/enum | Protocol, dataclass, enums | Kernel objects and provider contracts |
| jsonschema | Draft202012Validator(...).validate(payload) | Boundary schemas; domain rules remain explicit functions |
| anyio | create_task_group, fail_after, open_process, cancellation scopes | Local orchestration and bounded cancellation |
| hashlib | sha256 | Source/artifact/config/evidence hashes |
| sqlite3 | connect, transactions | Durable metadata and append-only event references |
| defusedxml.ElementTree | parse | JUnit parsing with size/schema constraints |
| pytest | pytest.main; collection/deselection/runtest reporting hooks | Trusted Python evaluator plugin |
| Hypothesis | RuleBasedStateMachine, rule, invariant, given | Lifecycle, lease, cancellation, approval and identity property tests |
| swe-rex, optional | DockerDeployment.start/stop; runtime().execute(Command(...)) | Container execution adapter; implementation smoke-test exact version |
| playwright, optional | async_playwright; chromium.launch; browser.new_context; tracing | Python-driven browser fixtures; native TS suites may use @playwright/test |
| openai, optional | AsyncOpenAI; client.responses.create | Direct API stage provider and tool-call loop |
| anthropic, optional | AsyncAnthropic; client.messages.create | Alternative direct API stage provider and tool-call loop |
| datasets, evaluation only | load_dataset with a pinned dataset revision | Optional public benchmark import |

An API response call alone is not a coding agent. API providers need bounded
tool execution, output validation, continuation, cancellation and transcript
capture. Tools are brokered through execution/authorization providers; API keys
are available to the control plane, not injected into the target environment.

Adapters for Node TAP, .NET TRX, Swift xcresult and other native reports can be
added later. The core accepts the common evidence contract, not those formats.

## 7. Repositories and reuse decisions

| Repository | Inspected or relevant locations | Use decision |
| --- | --- | --- |
| sps18209/ICM-HARNESS | kernel/contracts.py; application/service.py; evaluation/runner.py; workspace/identity.py; agents/factory.py | Refactor in place. Preserve lifecycle, leases, audit and existing clients |
| SWE-agent/SWE-ReX | src/swerex/deployment/abstract.py, docker.py; src/swerex/runtime/abstract.py | Optional dependency behind ExecutionProvider; not a copied runtime fork. Inspected MIT license; validate exact dependency revision |
| SWE-agent/mini-swe-agent | src/minisweagent/agents/default.py: DefaultAgent.run, step, query, execute_actions | Comparative baseline and design reference; optional wrapper after compatibility checks. Do not transplant its entire framework |
| SWE-bench/SWE-bench | swebench/harness/grading.py: test_passed, compute_fail_to_pass, compute_pass_to_pass, get_resolution_status | Benchmark integration and fail-to-pass/regression semantics; do not use benchmark grading as a universal product oracle |
| CUHK-Shenzhen-SE/UTBoost | Repository overview and UTGenerator workflow | Optional test-augmentation experiment, not a required runtime dependency. File-level reuse remains pending deeper inspection |
| pytest-dev/pytest | Public reporting and collection hooks | Depend on public APIs; do not copy private _pytest internals |
| HypothesisWorks/hypothesis | Stateful testing API | Dev dependency for control-plane state sequences |
| microsoft/playwright | Browser automation APIs and native test runner | Optional verification dependency |
| openai/openai-python | Official async Responses client | Optional provider dependency |
| anthropics/anthropic-sdk-python | Official async Messages client | Optional provider dependency |

Only ICM code is being modified in this plan. No external source has yet been
ported or installed for the implementation. Before copying external code, record
commit SHA, exact paths, license/notice obligations, dependencies, vulnerabilities
and the contract tests that justify reuse. Preserve required notices. Dataset
terms and underlying task-repository licenses require separate checks; a harness
repository's license does not settle rights to its benchmark tasks.

The inspected SWE-ReX root tree was
5c995c365dfb1fd5bc56fda688be5d8538f9931f. Resolve the corresponding release/commit
and pin it during implementation; a tree hash here is not a package version.

## 8. Models and roles

The engine has no mandatory model. Deterministic policy decides execution
completeness, identity consistency, skip authorization and promotion eligibility.
No model may override those decisions.

Starting evaluation candidates, not declared winners:

| Role | Starting candidate | Rule |
| --- | --- | --- |
| Routine planner/writer | GPT-6.1 Sol via current supported Codex or direct Responses provider | Measure correctness/cost before making it the default |
| Cross-provider comparison/review assistance | Claude Sonnet 5.5 via Claude CLI or Messages provider | A separate model is not automatically an independent authority |
| Difficult ambiguity/escalation | GPT-6 Astra or Claude Opus 5.5 | Explicit bounded escalation after evidence of need |
| Cheap routing/summarization experiments | GPT-6 Luna or Claude Haiku 5.5 | Must not decide acceptance; adopt only after task-specific evaluation |
| Offline enforcement checks | Deterministic injected agent | No live model needed |

Model catalog names were checked in official OpenAI and Anthropic documentation.
Resolve actual API IDs, account availability and pricing at implementation time;
record requested and returned model identity, provider, effort, tool settings,
prompt/version, token usage and cost. Pin snapshots when offered. Mutable aliases
must remain visible, and provider model revisions limit reproducibility.
Preserve current configured provider until comparative evidence warrants a change.
No custom model training, fine-tuning, embeddings or cross-client memory is
required. Provider data-retention settings must be configured for the actual
account; this plan does not assert vendor retention behavior.

## 9. Data, fixtures and experiments

First use owned synthetic fixtures: broken API validation, cross-tenant denial,
stale writes, missing collection, skip/deselection attacks, config/plugin changes,
forged reports, duplicate test IDs, failed imports, timeouts, process escape,
stale deployments, lease loss, concurrent approval and interrupted recovery.
Use fabricated data only. No client documents, PHI or personal-account datasets
are needed to validate this harness.

Maintain:
- tasks.jsonl: task ID, objective, family, repository revision and applicability.
- test-manifest.json: required/optional IDs and trusted input digests.
- run.json: configuration, candidate, environment, model and budget identities.
- events.jsonl plus content-addressed evidence blobs: executed operations/results.
- grading.json: separate deterministic verdict and any human/model interpretation.
- review.json: reviewer, candidate, findings and disposition.
- third-party-data.json: origin, revision, license review and permitted use.

Start with 12 deterministic integrity scenarios. Then prepare 30 representative
tasks: 10 Python API, 10 TypeScript API, 5 browser flows, 5 recovery/environment
tasks. Reserve 10 by task family as held-out evaluation; avoid near-duplicate
fixtures across splits. Acceptance material is withheld from the writer where
appropriate, while the required behavior remains explicit.

Optional external data: a small revision-pinned SWE-bench Lite/Verified subset,
then a multilingual subset if rights/environment checks pass. The official
dataset documentation names SWE-bench/SWE-bench_Verified on Hugging Face; resolve
the exact dataset revision and split rather than assuming aliases are stable.
These benchmarks measure repository-repair performance, not desktop/mobile or
production correctness across all software.

Comparison configurations: previous harness, hardened harness, simple repair loop.
Use the same tasks/model/budgets and repeated trials. First run 5 tasks x 3
configurations x 2 models x 2 repetitions = 60 episodes as a cost pilot. Expanding
to 30 x 3 x 2 x 3 = 540 episodes is contingent on the pilot, not preauthorized
spend. Record task success, false acceptance/rejection, integrity findings,
regressions, tokens, elapsed time, environment failures and repair attempts.
Report denominators and intervals; zero observed false accepts in a small sample
is not proof of zero risk. Use pass@1 as the initial live measure and report any
retry budget separately. Treat mutation experiments as deliberate faults with
known expected outcomes; do not introduce a blanket mutation-score threshold.

## 10. Migration map and PR sequence

| Existing location | Intended change |
| --- | --- |
| application/service.py | Gradually delegate acceptance, handoffs, verification and promotion to small services |
| evaluation/profile.py | Add versioned v2 profiles with explicit test manifests; reject unsafe skip semantics |
| evaluation/runner.py | Move OS/process behavior into LocalExecutionProvider and parsing into verifier adapters |
| workspace/identity.py | Implement GitCandidateProvider; add separate build/environment identity contracts |
| agents/codex_cli.py and claude_cli.py | Retain adapters and import compatibility; add direct API alternatives later |
| cli, mcp and web packages | Thin optional clients; move/re-export only after compatibility tests |
| kernel/state.py and application/artifacts.py | Keep SQLite/filesystem defaults; introduce append-only and blob-reference contracts |
| integrations/* | Keep existing optional integrations; do not enable E2B/Hatchet/etc. just because they exist |

PR 0: capture baseline, dependency/license inventory, regression metrics, ADR and
the reproduced skip-bypass test. Gate: an independently executable failing
reproduction exists and does not depend on live model access.

PR 1: required IDs, exact skip lists, trusted collection/events and evaluator
input integrity. Gate: unchanged protected test files cannot be bypassed through
collection/configuration changes; known optional live smoke remains explicit.

PR 2: domain contracts, provider ports and local-provider extraction. Gate: no
core imports of interface/vendor modules, current API/client behavior preserved,
local contract suite passes, existing candidate/approval checks unchanged.

PR 3: container execution and evaluator boundary. Gate: same acceptance scenarios
pass through local and container providers; writer cannot alter evaluator inputs
or receipts; cancellation and cleanup leave no live target processes/resources.
Record residual container/host trust limitations explicitly.

PR 4: TypeScript/API/browser fixtures and build/deployment identities. Gate:
cross-language tasks run without changing core decision rules; a stale build or
wrong deployment cannot inherit a source-only passing result.

PR 5: API agent providers and bounded tool broker. Gate: no CLI binary required
for the API path; keys absent from target environment; cancellation, tool limits,
structured-output recovery and resumption pass; acceptance stays deterministic.

PR 6: comparison runner, pilot tasks and independent review. Gate: measured
results with costs/uncertainty, material findings resolved or explicitly accepted
by the owner, no unsupported general-performance claim. Expand live trials only
after reviewing pilot costs and validity.

Each PR needs appropriate regression and adversarial checks. Use targeted
reviews throughout rather than waiting until the last PR. Keep changes reversible
through old entrypoint aliases and clear profile migration errors. Do not silently
translate blanket skip permission into an equivalent weakening in profile v2.

## 11. Acceptance conditions for the overall plan

- Required tests cannot disappear, be silently skipped, or be replaced by others.
- A successful command cannot establish a stronger behavioral claim by itself.
- Writer access cannot alter trusted acceptance material or evaluator authority.
- Verified source/build/environment identities match delivery identities.
- The same decision policy works through two real execution providers and two
  target languages without vendor imports in the core.
- Existing optional clients continue to work, and library use succeeds when CLI
  and MCP entrypoint packages are unavailable.
- Missing native/mobile/GPU capability blocks that work explicitly.
- Tests, repeated live-agent evidence and independent review are reported as
  different forms of evidence. Neither one substitutes for the others.

## 12. Sources checked

Current ICM source: https://github.com/sps18209/ICM-HARNESS/tree/723de3e283157d3beb4adc54613715862df3d3b5
SWE-ReX: https://github.com/SWE-agent/SWE-ReX
SWE-ReX API: https://swe-rex.com/latest/api/deployments/config/
mini-swe-agent: https://github.com/SWE-agent/mini-swe-agent
SWE-bench grading: https://github.com/SWE-bench/SWE-bench/blob/main/swebench/harness/grading.py
SWE-bench datasets: https://www.swebench.com/SWE-bench/guides/datasets/
UTBoost: https://github.com/CUHK-Shenzhen-SE/UTBoost
pytest hooks: https://docs.pytest.org/en/stable/_modules/_pytest/hookspec.html
pytest plugin control: https://docs.pytest.org/en/stable/how-to/plugins.html
Hypothesis stateful tests: https://hypothesis.readthedocs.io/en/latest/stateful.html
Playwright Python: https://playwright.dev/python/docs/api/class-browsertype
OpenAI models: https://developers.openai.com/api/docs/models
OpenAI SDK: https://github.com/openai/openai-python
Claude models: https://platform.claude.com/docs/en/models/overview
Anthropic SDK: https://github.com/anthropics/anthropic-sdk-python

Source API/function names were inspected where stated; planned ICM functions are
new contracts. Recommendations are engineering judgments informed by the earlier
RRA/research review. No dependency port, training run, platform adapter or live
experiment is claimed implemented by this document.
