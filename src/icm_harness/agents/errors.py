class StageAgentError(RuntimeError):
    """The configured stage agent could not produce a valid result."""


class StageCancelled(StageAgentError):
    """The operator cancelled a running stage."""
