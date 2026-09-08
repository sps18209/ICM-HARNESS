"""Approval-class taxonomy for consequential actions.

``policies/risk.py`` computes *whether* a human gate is required from a task's
stakes and reversibility. This module supplies the missing *why*: a small, named
vocabulary of approval classes, harvested from the Bounded Agent Organization
pattern (see ADR-0010). It sharpens the existing gate model without replacing it —
``requires_human_gate`` remains the risk-driven signal; an :class:`ApprovalClass`
labels the *kind* of authority a step is exercising.

The taxonomy is deliberately closed and ordered by escalating consequence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApprovalClass(Enum):
    """The kind of authority an action exercises, ordered by consequence.

    ``local_reversible`` is the only class safe to execute inside an active work
    item without a human gate; every other class must be prepared (draft, dry
    run, payload) and then gated.
    """

    LOCAL_REVERSIBLE = "local_reversible"
    PROJECT_SCOPE = "project_scope"
    EXTERNAL_ACTION = "external_action"
    DESTRUCTIVE = "destructive"
    SECURITY_SENSITIVE = "security_sensitive"

    @property
    def requires_human_approval(self) -> bool:
        """Whether an action of this class needs an explicit human gate."""
        return self is not ApprovalClass.LOCAL_REVERSIBLE


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """A description of an action awaiting classification.

    The flags mirror the distinctions the taxonomy draws. They are independent:
    an action may be both external and destructive (the higher class wins).
    """

    summary: str
    changes_approved_scope: bool = False
    touches_external_surface: bool = False
    is_destructive: bool = False
    is_security_sensitive: bool = False
    is_safe_local_inspection: bool = False


def classify(request: ActionRequest) -> ApprovalClass:
    """Map an action to its approval class.

    Precedence, highest consequence first: destructive, then security-sensitive
    (a safe local inspection inside scope is exempt from this one), then external
    action, then project-scope change, otherwise local and reversible.
    """
    if request.is_destructive:
        return ApprovalClass.DESTRUCTIVE
    if request.is_security_sensitive and not request.is_safe_local_inspection:
        return ApprovalClass.SECURITY_SENSITIVE
    if request.touches_external_surface:
        return ApprovalClass.EXTERNAL_ACTION
    if request.changes_approved_scope:
        return ApprovalClass.PROJECT_SCOPE
    return ApprovalClass.LOCAL_REVERSIBLE


def requires_human_gate(request: ActionRequest) -> bool:
    """Convenience: whether classifying ``request`` yields a gated class."""
    return classify(request).requires_human_approval
