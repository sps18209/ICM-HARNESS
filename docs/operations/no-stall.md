# No-Stall Runtime Policy

Every background stage requires:
- unique run id;
- resource lease and owner;
- heartbeat and expiry;
- wall-clock deadline;
- bounded retry policy;
- cancellation path;
- terminal or dead-letter state.

Transient retries occur inside a durable stage attempt.
Durable execution recovers across process/host failure.
