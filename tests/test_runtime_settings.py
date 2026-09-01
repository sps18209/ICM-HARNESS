from icm_harness.context.triggers import ContextTrigger
from icm_harness.policies.runtime_settings import SituationalSettingsPolicy


def test_writer_starts_narrow_and_escalates_only_on_trigger():
    policy = SituationalSettingsPolicy()
    base = policy.settings("build.writer", stakes=0.4)
    escalated = policy.settings(
        "build.writer", stakes=0.4, triggers=(ContextTrigger.CROSS_FILE_COUPLING,)
    )
    assert base.context_tier == 2
    assert escalated.context_tier == 3
    assert escalated.max_tool_calls > base.max_tool_calls


def test_tool_output_pressure_does_not_increase_tool_budget():
    policy = SituationalSettingsPolicy()
    base = policy.settings("discovery.research", stakes=0.5)
    pressure = policy.settings(
        "discovery.research", stakes=0.5, triggers=(ContextTrigger.TOOL_OUTPUT_TOO_LARGE,)
    )
    assert pressure.max_tool_calls <= base.max_tool_calls
