# Design spec: LLM-guided intake

**Status:** Draft for review. Not yet implemented. If accepted, graduates into
an ADR and a build slice.

**Problem owner's ask:** a person should be able to start a round by describing
what they want in plain language — *"hey, I want to build an app that tracks my
runs"* — and be guided the rest of the way by a short conversation. No form,
no numeric knobs, no knowledge of code required. Power-user shortcuts come
later, only once someone wants them.

---

## 1. Why this is a small change, not a rewrite

Routing is already fully automatic and deterministic. `routing.mode_router`
reads five signals off a `TaskProfile` — `specification_clarity`,
`epistemic_uncertainty`, `stakes`, `reversibility`, `production_change_required`
— and picks the mode with no model in the loop.

The friction is only in **where those signals come from**. Today
`cli._profile_from_args` fills them from CLI flags that default to `0.5`. So a
newcomer who types

```
icm new "build me a run tracker"
```

hands over an all-`0.5` profile, the router cannot tell what kind of work this
is, and it falls through to its catch-all branch (`"default: unresolved
epistemic uncertainty"` → discovery). **That default-`0.5` form is the thing we
are removing.**

The fix inserts one step:

```
              TODAY
  request ──► flags/defaults ──► TaskProfile ──► router ──► stages

              PROPOSED
  request ──► [ LLM-guided intake ] ──► TaskProfile ──► router ──► stages
                      ▲   │
                      └───┘  short guided chat (2–4 questions)
```

Everything to the right of `TaskProfile` is untouched — the router, the modes,
the stage agents, worktree isolation. We are only replacing **who fills in the
profile**: an LLM plus a short conversation, instead of a human typing numbers.

### Alignment with the harness's own rules

- **"No model in the scoring loop" is preserved.** That rule governs *verdicts*
  (grading, gates, matching). Interpreting what a person wants is *content
  interpretation* — explicitly the model's job. The intake LLM produces a
  proposed profile; a deterministic step validates and clamps it; the
  deterministic router turns it into a mode. The model proposes, the code
  decides.
- **Adapters, not domain logic** (ADR-0007): intake reuses the existing agent
  transport (`claude-cli` by default) for its one LLM call. It adds no new
  provider coupling.

---

## 2. The intake concern

A new top-level module, `src/icm_harness/intake/`, sitting **upstream of
routing**: routing decides a mode *from* a profile; intake *produces* the
profile. It is not a stage — it never runs inside the round lifecycle, so it
does not touch leases, worktrees, or gates.

```
intake/
  __init__.py         # barrel (public: run_intake, IntakeResult, IntakeQuestion)
  agent.py            # the single structured LLM call
  conversation.py     # deterministic loop: ask questions, collect answers, finalize
  contracts.py        # IntakeResult / IntakeQuestion / IntakeProfileDraft
```

Dependencies: `kernel` (TaskProfile), `agents` (via its barrel, for the LLM
call), `config`. No import of `integrations` (Rule A holds). Add `intake` to
`MODULES.md`, `BARREL_ENFORCED`, and `TOP_MODULES` in
`scripts/validate_architecture.py`.

> **Refactor note.** `agents/claude_cli.py` already knows how to run
> `claude -p --output-format json`, unwrap the envelope's `result`, and salvage
> a fenced JSON object. The intake agent needs the same envelope handling for a
> *non-stage* one-shot call. Factor `_unwrap_envelope` + `_extract_stage_json`
> into a shared `agents` helper both can call, rather than duplicating.

### 2.1 The intake LLM call — contract

**Input** (kept minimal in v1):
- the raw request string;
- a few environment facts: is this a git repo, primary language(s) present in
  the tree, and whether a Context Wiki exists. (What, if any, deeper repo
  context to read is an open question — see §7.)

**Output** (structured JSON, validated against a schema exactly like the stage
contract):
```jsonc
{
  "restated_objective": "Build a personal running-log app…",   // plain-English echo
  "profile_draft": {                    // the LLM's best inference, every field
    "intent": "build",
    "specification_clarity": 0.35,
    "epistemic_uncertainty": 0.6,
    "stakes": 0.4,
    "reversibility": 0.8,
    "production_change_required": false,
    "code_intensity": 0.7,
    "research_intensity": 0.2,
    "tool_intensity": 0.1
  },
  "questions": [                        // 2–4, chosen for THIS request
    {
      "id": "surface",
      "prompt": "Who is this for?",
      "choices": [
        {"label": "Just me, experimenting",        "sets": {"stakes": 0.2, "production_change_required": false}},
        {"label": "Something real people will use", "sets": {"stakes": 0.7, "production_change_required": true}},
        {"label": "Not sure yet",                   "sets": {}}
      ],
      "recommended": 0
    }
    // …
  ]
}
```

Each **question** is plain English, offers **multiple-choice answers** (so the
person picks, never types a number), carries a `recommended` default, and — this
is the load-bearing part — each choice declares which profile fields it `sets`.
That keeps the *mapping from answer → numeric signal deterministic and
inspectable*: the LLM writes the questions and the answer→field mapping up
front, and the code applies the chosen `sets` verbatim. The model never silently
re-scores after the fact.

---

## 3. The guided conversation (the UX)

Chosen interaction model: **always a short guided chat** (2–4 questions) for an
interactive `icm new` with a bare objective.

```
$ icm new "I want to build an app that tracks my runs"

Let's shape this. (3 quick questions — press Enter to accept the suggestion.)

  1) Who is this for?
       > [1] Just me, experimenting        ← suggested
         [2] Something real people will use
         [3] Not sure yet
     ‹enter›

  2) Do you already know roughly how it should work?
       > [1] Yes, I can describe it
         [2] Partly — some of it is figuring-out    ← suggested
         [3] No, that's part of the job
     2

  3) How big is this first step?
       > [1] One small thing               ← suggested
         [2] A bigger, multi-part build
     2

Here's the plan:
  “Build a personal running-log app; scope and approach are partly open.”
  → I'll run this as a DISCOVERY → BUILD task (figure out the shape, then build it).

  [Enter] run it   ·   [e] change an answer   ·   [q] cancel
```

- Questions are asked **one at a time**, numbered choices, Enter = recommended.
- The final screen **restates the objective in plain English** and names the
  mode in plain English (never "epistemic_uncertainty = 0.6").
- No code vocabulary anywhere in the novice path.

### Escape hatches (the "pro" path)

- **Any explicit profile flag** on `icm new` (`--intent`, `--stakes`, …) →
  intake is skipped entirely; current flag behavior is preserved unchanged.
- **`-y` / `--yes`** → accept the LLM's inferred draft, skip the questions
  (once you trust it).
- **`--no-intake`** → force the old flag/default behavior.
- **Non-interactive stdin** (CI, piped, `--json` without a TTY) → never block on
  a human: use the inferred draft + safe defaults and record that intake ran
  headless. Guided chat is for humans at a terminal only.

Shortcut keys (your "only after being pro" point) layer on top later — the same
choices bound to number keys / a `fzf`-style picker — without changing the model.

---

## 4. How an answer becomes a mode (worked examples)

The plain questions map onto the router's existing signals. The LLM chooses
*which* 2–4 questions matter for the specific request; these are the common
shapes:

| Plain question | Signals it sets | Why the router cares |
|---|---|---|
| "Who is this for?" | `stakes`, `production_change_required` | high stakes + prod → build, not quick |
| "Do you know how it should work?" | `specification_clarity`, `epistemic_uncertainty` | low clarity/high uncertainty → discovery first |
| "How big is this step?" | `code_intensity`, scope | routes quick vs build |
| "Is this reviewing/deciding, or making something?" | `intent` | review / decision modes |

Resulting routes, end to end from plain English:

- *"fix the typo in the footer"* → clear, tiny, reversible → **quick**.
- *"build a run tracker, not sure how yet"* → low clarity, build intent →
  **discovery → build**.
- *"should we use Postgres or SQLite for this?"* → decide intent → **decision**.
- *"look over this PR"* → review intent → **review**.

The mapping is the *existing* deterministic router. Intake's only new job is
turning words into the signals it already consumes.

---

## 5. Failure & honesty

- Intake LLM call errors or returns off-contract → **do not fail the command.**
  Fall back to a deterministic default profile (`intent=auto`, defaults), tell
  the user *"couldn't analyze that automatically — running with safe defaults;
  refine with flags if needed,"* and proceed. Intake is an assist, never a gate.
- Intake is **one cheap model call**; it is logged and cost-attributed like any
  other, and shown in the round's cost line.
- The restated objective is a **confirmation checkpoint** — the person sees what
  the machine understood before anything runs, which is how an abstract request
  gets caught if it was misread.

---

## 6. Testing

- **Hermetic**: a fake intake agent (mirroring the fake-`claude` pattern in
  `test_claude_agent.py`) returns canned drafts + questions. Assert: the CLI
  asks exactly those questions, applies the chosen `sets`, builds the expected
  `TaskProfile`, and the router picks the expected mode. Cover the escape
  hatches (flags bypass, `-y`, non-interactive fallback) and the off-contract
  fallback.
- **Golden routing table**: (plain request → expected mode) pairs run through
  the fake agent, guarding the four worked examples in §4 against regressions.
- **Optional live eval** (Phase 3): a small labelled set of real requests scored
  for "did intake route it correctly," plugged into an eval harness — measures
  intake accuracy with real models without gating CI.

---

## 7. Open questions for review

1. **Default-on or opt-in first?** Ship guided intake as the default for a bare
   `icm new`, or behind `--intake` / a config flag for one release while it
   proves out? (Recommendation: default-on for interactive TTY, since the
   escape hatches fully preserve the old path.)
2. **How much repo context should intake read?** Nothing / cwd + languages /
   the Context Wiki summary. More context sharpens inference but costs latency
   and widens what leaves the machine. (Recommendation: v1 reads only cwd +
   language detection; Context Wiki is Phase 2.)
3. **Question count.** Hard cap at 4, or let the LLM ask fewer when the request
   is already clear even though the chosen model is "always chat"? (Recommend:
   floor of 1, cap of 4; a fully-specified request still gets one confirmation.)
4. **Model for intake.** Always the configured agent's model, or a small/fast
   model for the intake call regardless of the round's model? (Recommend: a
   fast model — intake is classification-shaped.)

---

## 8. Phasing

- **Phase 1 (first build slice):** the `intake/` module, the CLI guided chat,
  escape hatches, fallback, hermetic + golden tests. CLI only.
- **Phase 2:** surface the same intake in the web operator console (a chat
  panel) and, optionally, feed the Context Wiki into inference.
- **Phase 3:** the live intake-accuracy eval set + shortcut-key bindings for the
  question picker.

---

## 9. Definition of done (Phase 1)

- `icm new "any plain-English idea"` with no flags opens a ≤4-question chat,
  confirms a restated objective, and runs the correctly-routed round.
- Every existing flag path and `--dry-run` behave exactly as before.
- Non-interactive and error paths never hang and never hard-fail on intake.
- `ruff`, the full suite, and both architecture/layout validators stay green;
  `intake` is registered in the module map and the validators.
