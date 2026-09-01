from icm_harness.kernel.contracts import Mode, ModeRoute, TaskIntent, TaskProfile


class ModeRouter:
    def route(self, task: TaskProfile) -> ModeRoute:
        if task.intent is TaskIntent.QUICK:
            return ModeRoute((Mode.QUICK,), "explicit quick intent")
        if task.intent is TaskIntent.REVIEW:
            return ModeRoute((Mode.REVIEW,), "explicit review intent")
        if task.intent is TaskIntent.DECIDE:
            return ModeRoute((Mode.DECISION,), "explicit decision intent")
        if task.intent is TaskIntent.INVESTIGATE:
            return ModeRoute((Mode.DISCOVERY,), "explicit investigation intent")
        if task.intent is TaskIntent.BUILD:
            return self._route_build(task)

        if (
            task.production_change_required
            and task.specification_clarity >= 0.80
            and task.epistemic_uncertainty <= 0.25
            and task.stakes <= 0.35
            and task.reversibility >= 0.80
        ):
            return ModeRoute((Mode.QUICK,), "small, clear, low-risk reversible production change")
        if task.production_change_required:
            return self._route_build(task)
        if task.specification_clarity >= 0.8 and task.epistemic_uncertainty <= 0.2:
            return ModeRoute((Mode.QUICK,), "clear non-production task")
        return ModeRoute((Mode.DISCOVERY,), "default: unresolved epistemic uncertainty")

    def _route_build(self, task: TaskProfile) -> ModeRoute:
        if (
            task.epistemic_uncertainty > 0.35
            or task.specification_clarity < 0.70
            or task.stakes >= 0.80
        ):
            return ModeRoute(
                (Mode.DISCOVERY, Mode.BUILD),
                "implementation required, but premises/architecture require discovery first",
            )
        return ModeRoute((Mode.BUILD,), "requirements sufficiently resolved for build mode")
