# Concurrency Policy

Recommended defaults:
- read-only discovery: 6-8 per round;
- research: bounded fan-out;
- Writer: one per worktree;
- Tester: bounded test sharding;
- Context Wiki promotion: one per project;
- merge/rebase: one per repository.

Local enforcement: AnyIO + SQLite leases.
Distributed enforcement: Hatchet/Temporal-equivalent dynamic concurrency keys.
