from icm_harness.kernel.contracts import Mode, ModeRoute, ModeSpec, StageSpec

DISCOVERY = ModeSpec(
    Mode.DISCOVERY,
    (
        StageSpec(Mode.DISCOVERY, "frame", required_outputs=("frame.md",)),
        StageSpec(Mode.DISCOVERY, "explore", required_outputs=("explore-tree.md",)),
        StageSpec(
            Mode.DISCOVERY, "research", default_context_tier=2, required_outputs=("evidence.md",)
        ),
        StageSpec(
            Mode.DISCOVERY,
            "adversarial",
            default_context_tier=2,
            required_outputs=("adversarial.md",),
        ),
        StageSpec(Mode.DISCOVERY, "synthesis", required_outputs=("synthesis.md",)),
        StageSpec(Mode.DISCOVERY, "validate", required_outputs=("validation.md",)),
    ),
)

BUILD = ModeSpec(
    Mode.BUILD,
    (
        StageSpec(
            Mode.BUILD,
            "planner",
            default_context_tier=2,
            required_outputs=("execution-plan.md", "context-manifest.json"),
        ),
        StageSpec(
            Mode.BUILD,
            "writer",
            mutates_workspace=True,
            required_outputs=("change-manifest.json", "implementation-notes.md"),
            permitted_return_stages=("build.planner",),
        ),
        StageSpec(
            Mode.BUILD,
            "tester",
            default_context_tier=2,
            required_outputs=("test-report.json",),
            permitted_return_stages=("build.writer", "build.planner"),
        ),
        StageSpec(
            Mode.BUILD, "close", mutates_workspace=True, required_outputs=("final-record.md",)
        ),
    ),
)

DECISION = ModeSpec(
    Mode.DECISION,
    (
        StageSpec(Mode.DECISION, "frame", required_outputs=("decision-frame.md",)),
        StageSpec(
            Mode.DECISION,
            "evidence",
            default_context_tier=2,
            required_outputs=("decision-evidence.md",),
        ),
        StageSpec(Mode.DECISION, "options", required_outputs=("options.md",)),
        StageSpec(
            Mode.DECISION,
            "adversarial",
            default_context_tier=2,
            required_outputs=("decision-adversarial.md",),
        ),
        StageSpec(
            Mode.DECISION, "decide", requires_human_gate=True, required_outputs=("decision.md",)
        ),
        StageSpec(Mode.DECISION, "validate", required_outputs=("decision-validation.md",)),
        StageSpec(Mode.DECISION, "close", required_outputs=("decision-record.md",)),
    ),
)

REVIEW = ModeSpec(
    Mode.REVIEW,
    (
        StageSpec(Mode.REVIEW, "ingest", required_outputs=("review-input.md",)),
        StageSpec(Mode.REVIEW, "reconstruct", required_outputs=("reconstruction.md",)),
        StageSpec(
            Mode.REVIEW, "inspect", default_context_tier=2, required_outputs=("inspection.md",)
        ),
        StageSpec(Mode.REVIEW, "adversarial", required_outputs=("review-adversarial.md",)),
        StageSpec(Mode.REVIEW, "findings", required_outputs=("findings.md",)),
    ),
)

QUICK = ModeSpec(
    Mode.QUICK,
    (
        StageSpec(
            Mode.QUICK,
            "execute",
            mutates_workspace=True,
            required_outputs=("change-manifest.json", "implementation-notes.md"),
        ),
        StageSpec(Mode.QUICK, "verify", required_outputs=("test-report.json",)),
        StageSpec(
            Mode.QUICK, "close", mutates_workspace=True, required_outputs=("final-record.md",)
        ),
    ),
)

CATALOG = {x.mode: x for x in (DISCOVERY, BUILD, DECISION, REVIEW, QUICK)}


def stage_refs_for_route(route: ModeRoute) -> tuple[str, ...]:
    return tuple(stage.ref for mode in route.modes for stage in CATALOG[mode].stages)


def get_stage(ref: str) -> StageSpec:
    mode_name, stage_name = ref.split(".", 1)
    for stage in CATALOG[Mode(mode_name)].stages:
        if stage.name == stage_name:
            return stage
    raise KeyError(ref)
