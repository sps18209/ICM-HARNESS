"""Architectural fitness functions (fail CI on a boundary breach).

Three rules are enforced over ``src/icm_harness``:

A. Adapter isolation — core modules must never import ``integrations``. Adapters
   depend on core contracts, never the reverse (see ADR-0007).
B. Public interface (barrel) boundary — a module may import a *feature* sibling
   only through its package barrel (``icm_harness.<feature>``), never by reaching
   into a private submodule (``icm_harness.<feature>.<submodule>``). ``kernel`` is
   the shared primitive layer and is exempt as a target: its submodules
   (``contracts``, ``errors``, ``state``, ``lifecycle``) are its public surface.
   Imports within a module's own package are unrestricted.
C. Acyclic dependency graph — the internal module dependency graph must be a DAG.

Run: ``python scripts/validate_architecture.py``
"""

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/icm_harness"

# Feature modules whose internals are private behind a barrel (Rule B targets).
# kernel (primitives) and integrations (adapters, Rule A) are deliberately absent.
BARREL_ENFORCED = {
    "modes", "policies", "context", "routing", "execution", "workspace",
    "agents", "memory", "evaluation", "observability", "intake", "cli", "web",
}
# Core cognitive modules that must not import adapters (Rule A).
CORE_MODULES = {
    "kernel", "modes", "policies", "context", "routing", "execution",
    "workspace", "agents", "memory", "evaluation", "observability", "intake",
}
FORBIDDEN_ADAPTER_PREFIX = "icm_harness.integrations"
# Every internal top-level module, for the dependency-graph check (Rule C).
TOP_MODULES = CORE_MODULES | {"integrations", "cli", "mcp", "web", "application"}


def _own_top(path: Path) -> str:
    parts = path.relative_to(CORE).parts
    return parts[0] if len(parts) > 1 else f"<{path.stem}>"


def _imports(tree: ast.AST) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(alias.name, node.lineno) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module, node.lineno))
    return out


errors: list[str] = []
edges: set[tuple[str, str]] = set()

for path in CORE.rglob("*.py"):
    own = _own_top(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for module, lineno in _imports(tree):
        if not module.startswith("icm_harness."):
            continue
        comps = module.split(".")
        if len(comps) < 2:
            continue
        target = comps[1]
        rel = path.relative_to(ROOT)

        # Rule A: core must not import adapters.
        if own in CORE_MODULES and module.startswith(FORBIDDEN_ADAPTER_PREFIX):
            errors.append(f"[adapter-isolation] {rel}:{lineno} imports adapter {module}")

        # Rule B: features are reachable only through their barrel.
        if target in BARREL_ENFORCED and target != own and len(comps) > 2:
            errors.append(
                f"[barrel] {rel}:{lineno} reaches into private submodule "
                f"{module}; import from icm_harness.{target} instead"
            )

        # Rule C: record an internal dependency edge.
        if target in TOP_MODULES and target != own:
            edges.add((own, target))

# Rule C: detect cycles via DFS over the module graph.
graph: dict[str, set[str]] = defaultdict(set)
for src_mod, dst_mod in edges:
    graph[src_mod].add(dst_mod)

WHITE, GREY, BLACK = 0, 1, 2
color: dict[str, int] = defaultdict(int)
cycles: list[list[str]] = []


def _visit(node: str, stack: list[str]) -> None:
    color[node] = GREY
    stack.append(node)
    for nxt in sorted(graph[node]):
        if color[nxt] == GREY:
            cycles.append(stack[stack.index(nxt):] + [nxt])
        elif color[nxt] == WHITE:
            _visit(nxt, stack)
    stack.pop()
    color[node] = BLACK


for node in sorted(graph):
    if color[node] == WHITE:
        _visit(node, [])

seen_cycles: set[frozenset[str]] = set()
for cycle in cycles:
    key = frozenset(cycle[:-1])
    if key in seen_cycles:
        continue
    seen_cycles.add(key)
    errors.append("[dag] dependency cycle: " + " -> ".join(cycle))

if errors:
    print("\n".join(sorted(errors)))
    raise SystemExit(1)
print("architecture: OK (adapter isolation, barrel boundaries, acyclic graph)")
