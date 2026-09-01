# Architecture Overview

The harness is a custom ICM control plane over replaceable runtime components.

Custom code owns mode semantics, stage contracts, context escalation, model-routing policy,
state/lease semantics, worktree isolation, evaluation/reward attribution, and Context Wiki promotion.

Adapters own provider transport, semantic code retrieval, durable workflow integration,
sandboxing, observability backends, and external eval tooling.
