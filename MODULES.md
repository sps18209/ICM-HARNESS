# Module Ownership Map

| Module | Owns | Must not own |
|---|---|---|
| `kernel` | contracts, state, lifecycle, leases | provider APIs |
| `modes` | stage topology and role boundaries | model selection |
| `policies` | rigor, risk, authorization overlays | workflow transport |
| `context` | budget, retrieval contracts, ranking, escalation | provider SDK behavior |
| `routing` | mode/model decision policy, Bayesian learning | API transport |
| `execution` | timeout, cancellation, retries, local concurrency | cognitive logic |
| `workspace` | Git/worktree/checkpoint/promotion mechanics | LLM logic |
| `agents` | stage-agent interface and role invariants | provider routing |
| `memory` | namespaced persistence | durable truth promotion |
| `evaluation` | gates and reward attribution | implementation repair |
| `observability` | audit/metric emission | routing decisions |
| `integrations` | external adapters | ICM business logic |
| `cli` | operator interface | hidden domain logic |
