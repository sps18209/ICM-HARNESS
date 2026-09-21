# Integration analysis: TypeSafe Jev (System One model)

Status: Points 1–3 implemented in
`src/icm_harness/integrations/typesafe/adapter.py`, each opt-in with
`TYPESAFE_API_KEY` set and the `systemone` extras installed: intake via
`[intake] profiler = "typesafe"`; the semantic stage gate and the
pre-promotion diff review via `[evaluation] semantic_gate` /
`promotion_review = "typesafe"` (both advisory — recorded as
`semantic_gate` / `promotion_reviewed` events, never able to pass a
stage or approve a merge). Point 4 (context ranking) remains proposed.

## What Jev is

[Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev) is
TypeSafe AI's "System One" model: instead of generating text, it takes a blob
of unstructured **state** plus a set of typed **questions** and returns
structured, calibrated answers in one parallel evaluation. Three primitives:

| Question type | Asks | Returns |
| --- | --- | --- |
| `choice` | pick one option from a labeled list | choice + per-option probabilities + confidence |
| `score` | rate the state on a rubric | score + confidence |
| `noul` | is this statement true? | probability 0–1 |

The economics are the point: ~70–500 ms end-to-end and roughly two orders of
magnitude cheaper than a frontier LLM call, with schema conformance guaranteed
by construction (it cannot emit free-form strings at all). The vendor's own
framing — "smart if-statements", classification/routing/scoring/guardrails —
is exactly the shape of several seams this harness already has.

Interface: `POST https://api.typesafe.ai/v1/systemone` with
`Authorization: Bearer $TYPESAFE_API_KEY`, model id `jev-latest`; Python SDK
`typesafe-sdk` (Python ≥ 3.10, ours is ≥ 3.11). Currently early access /
waitlist-gated.

## Why it fits this architecture specifically

The harness already enforces the split Jev assumes: **models propose signals,
deterministic code decides** (see `intake/agent.py`'s docstring and
ADR-0008). Every decision surface below consumes 0–1 scalars, enum choices, or
booleans — never prose. Jev produces exactly those, with calibrated
probabilities the harness can thread into routing and gating, which today's
LLM-emitted JSON numbers only pretend to be.

Per ADR-0007 and the module map, Jev enters as a **replaceable adapter under
`integrations/` only** (`src/icm_harness/integrations/typesafe/adapter.py`),
opt-in, raising `IntegrationUnavailable` when `typesafe-sdk` is absent —
same pattern as the River and Portkey adapters. Core modules must not import
it.

## Ranked integration points

### 1. Intake profiling — `intake/agent.py` (best fit; do this first)

Intake is today a single headless `claude` CLI call whose job is pure
classification: turn a plain-English request into a `TaskProfile` draft. That
draft is literally Jev's question set, one call, evaluated in parallel:

- `intent` → one `choice` over the six `TaskIntent` values;
- the seven float fields (`specification_clarity`, `epistemic_uncertainty`,
  `stakes`, `reversibility`, `code_intensity`, `research_intensity`,
  `tool_intensity`) → seven `score` questions with rubric criteria;
- `production_change_required`, `privacy_restricted` → two `noul`s.

The deterministic `finalize()` and the "code decides" boundary stay untouched;
only the proposer changes. Concrete wins:

- **Latency**: a CLI subprocess round-trip (seconds) becomes ~100 ms, which
  matters because intake sits between the user typing an objective and the
  first question they see.
- **Calibration drives the conversation.** Intake asks 2–4 clarifying
  questions. Today the LLM invents which ones matter; with Jev, per-field
  confidence tells us directly: ask about exactly the fields whose confidence
  is low, skip the rest. That turns the guided conversation from vibes into a
  measurement — and `docs/design/llm-guided-intake.md`'s question budget
  becomes a threshold on confidence rather than a fixed count.
- **No parse failures.** `propose()` currently guards against malformed JSON
  and falls back to flag defaults; Jev's answers are typed by construction,
  so that failure mode disappears (the transport failure path stays).

Caveat: Jev cannot author the plain-English clarifying questions themselves
(it does not generate text). Either keep a small LLM call for question
wording, or ship a fixed per-field question template keyed by which fields
scored low-confidence. The template route removes the LLM from intake
entirely and is probably good enough — the fields are stable and few.

Mechanically, `propose()` already takes an injectable `agent_fn`; the adapter
slots in beside it as an alternative proposer selected by `[intake]` config
(e.g. `profiler = "typesafe"`), with the existing CLI path as fallback.

### 2. Semantic stage gates — `evaluation/gates.py`

`validate_stage_outputs()` checks only that required output files exist. A
Jev call per stage transition is cheap enough to add *semantic* gating
without changing the gate's shape:

- `noul`: "this plan addresses the stated objective";
- `noul`: "the tester output reports actual verification, not a claim of it";
- `score`: output quality on a rubric per stage role.

Feed the graded result into `StageSignals` (`evaluation/rewards.py`) so
reward attribution — and therefore the Bayesian model-routing posteriors —
learn from output *quality*, not just the binary `gate_passed`. This is the
vendor's headline "verification/guardrails of LLM outputs" use case, and it
strengthens the harness's independent-evaluation invariant precisely because
the grader is a different model class from the agent that did the work.

### 3. Pre-promotion guardrail — `workspace/promotion.py` + `policies/`

Before a round's worktree is promoted, a `noul` sweep over the diff summary:
"this change stays within the declared write scope", "this diff touches
production configuration", "this change is consistent with the approved
plan". These back the ADR-0010 write-scope/approval-class policies with a
second opinion that costs milliseconds. The deterministic `assess_risk()`
formula stays authoritative — Jev only supplies an extra signal that can
*raise* (never lower) the required approval class.

### 4. Context ranking signals — `context/ranking.py` (later; batch-shaped)

`ContextRanker` combines six per-item relevance scalars that must come from
somewhere upstream. Scoring candidate context items against the stage
objective is Jev's map-reduce use case (many small states, same questions),
but volume × per-call latency means this wants batching and caching design
first. Worth a follow-up spike, not the first integration.

## Where Jev must NOT go

- **`routing/mode_router.py` and `routing/model_router.py`** stay
  deterministic. ADR-0008 is explicit: hard constraints, then utility math.
  Jev improves these routers' *inputs* (via intake, point 1), never replaces
  them.
- **`routing/learning.py`** — the Bayesian performance store and the River
  bandit are the harness's own numerics; nothing to delegate.
- **Any mutating stage.** Jev cannot write code or text; it is not an agent
  provider and does not belong in `agents/`.

## Adapter mechanics (when implemented)

- Location: `src/icm_harness/integrations/typesafe/adapter.py`, exporting a
  thin client (`ask(state, questions) -> answers`) plus the intake-shaped
  proposer built on it. Lazy import of `typesafe-sdk`, raising
  `IntegrationUnavailable` with the install hint, matching
  `integrations/river/adapter.py`.
- Packaging: new extras group in `pyproject.toml`, e.g.
  `systemone = ["typesafe-sdk>=X"]` (pin after license/version review, per
  the source-map rule).
- Auth: `TYPESAFE_API_KEY` env var (SDK default), surfaced in
  `.env.example`; `icm doctor` should report presence, never the value.
- **Privacy boundary**: intake state is the user's raw request text and a
  task's `privacy_restricted` / `max_privacy_class` exists for a reason. The
  adapter must be skipped (falling back to the local CLI path) whenever the
  task is privacy-restricted or the operator hasn't opted in — the same
  eligibility discipline `ModelRouter._eligible` applies to model candidates.
- Dry-run: `icm-dry on` must also stub Jev; the adapter needs a deterministic
  stand-in like the `dry-run` agent provider.

## Open questions / risks

- Early access: API is waitlist-gated; no SLA published. The fallback path
  (current CLI intake) must remain first-class, not vestigial.
- Vendor calibration claims are unverified by us; before wiring confidence
  into question-skipping or gate thresholds, run a small offline eval against
  the existing intake on recorded objectives (promptfoo adapter is already in
  the tree for exactly this).
- Score-question cardinality is capped (choices ≤ 255; scores use small
  rubrics); our 0–1 float fields need a rubric→scalar mapping convention
  (e.g. 5-point rubric normalized to 0–1) decided once and shared by all
  call sites.
