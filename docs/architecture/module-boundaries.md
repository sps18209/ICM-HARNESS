# Module Boundaries

The module graph is a doctrine, not a convention: it is enforced in CI by
`scripts/validate_architecture.py`, which fails the build on any breach.

## Layers

- `kernel` is the shared **primitive** layer: contracts, state, lifecycle,
  errors, leases. It may depend on nothing internal (it is the sink of the
  dependency graph). Its submodules are its public surface.
- The **feature** modules — `modes`, `policies`, `context`, `routing`,
  `execution`, `workspace`, `agents`, `memory`, `evaluation`, `observability`
  (plus the `cli` and `web` operator surfaces) — are bounded contexts. Each may
  depend on `kernel`.
- `application` (and the `cli`/`web`/`mcp` entrypoints) is the **wiring** layer
  that composes the features.
- `integrations` holds adapters that implement public core contracts.

## Enforced rules

1. **Adapter isolation.** Core modules must never import `integrations`. This
   keeps Portkey, Hatchet, Serena, River, Promptfoo, OpenLIT, E2B, MCP, and
   future replacements from becoming cognitive-architecture dependencies (see
   ADR-0007).
2. **Public interface (barrel) boundary.** A feature module is reachable from
   outside only through its package barrel — `from icm_harness.<feature> import X`
   — never by reaching into a private submodule
   (`icm_harness.<feature>.<submodule>`). Barrels resolve lazily (PEP 562) so the
   boundary adds no import-time coupling. `kernel` is exempt as a target: it is
   the primitive layer and its submodules are public.
3. **Acyclic dependency graph.** The internal module graph must be a DAG. Because
   `kernel` is a pure sink, orchestration that needs a feature (e.g.
   `RoundController` needing the `modes` stage catalog) receives it by injection
   from the wiring layer rather than importing the feature from `kernel`.
