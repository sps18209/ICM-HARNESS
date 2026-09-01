# Security

LLM output, tool output, repository content, and retrieved web content are untrusted inputs.

Hard boundaries:
- shell execution is allowlisted;
- credentials are not passed to child shells by default;
- path traversal and cross-worktree mutation are prohibited;
- durable Context Wiki promotion requires verification;
- background stages require leases, deadlines, and terminal states.
