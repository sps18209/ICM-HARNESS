class HarnessError(Exception):
    """Base harness error."""


class ContractViolation(HarnessError):
    """A stage or adapter violated an explicit contract."""


class InvalidTransition(HarnessError):
    """A requested lifecycle transition is not allowed."""


class LeaseUnavailable(HarnessError):
    """A protected resource is currently leased by another worker."""


class LeaseLost(HarnessError):
    """The worker no longer owns its lease."""


class ContextBudgetExceeded(HarnessError):
    """Required context cannot fit the permitted budget."""


class NoEligibleModel(HarnessError):
    """No model satisfies hard routing constraints."""


class IntegrationUnavailable(HarnessError):
    """An optional integration is not installed or configured."""


class WorkspaceError(HarnessError):
    """Workspace or Git isolation operation failed."""
