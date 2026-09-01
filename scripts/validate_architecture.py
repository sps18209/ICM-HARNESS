import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/icm_harness"
FORBIDDEN_PREFIX = "icm_harness.integrations"

errors = []
for module_dir in ("kernel", "modes", "policies", "context", "routing", "execution",
                   "workspace", "agents", "memory", "evaluation", "observability"):
    for path in (CORE / module_dir).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(FORBIDDEN_PREFIX):
                    errors.append(f"{path.relative_to(ROOT)} imports forbidden adapter {name}")

if errors:
    print("\n".join(errors))
    raise SystemExit(1)
print("architecture imports: OK")
