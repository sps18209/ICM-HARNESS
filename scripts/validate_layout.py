from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
required = [
    "src/icm_harness/kernel",
    "src/icm_harness/modes",
    "src/icm_harness/policies",
    "src/icm_harness/context",
    "src/icm_harness/routing",
    "src/icm_harness/execution",
    "src/icm_harness/workspace",
    "src/icm_harness/agents",
    "src/icm_harness/memory",
    "src/icm_harness/evaluation",
    "src/icm_harness/observability",
    "src/icm_harness/integrations",
    "workspace_template/0_Context_Wiki",
    "workspace_template/1_Modes",
    "docs/decisions",
]
missing = [x for x in required if not (ROOT / x).exists()]
if missing:
    raise SystemExit("missing required paths: " + ", ".join(missing))
print("layout: OK")
