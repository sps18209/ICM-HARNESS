from enum import StrEnum


class ContextTrigger(StrEnum):
    CONTEXT_GAP = "context_gap"
    ARCHITECTURE_UNKNOWN = "architecture_unknown"
    CROSS_FILE_COUPLING = "cross_file_coupling"
    TEST_FAILURE_PLAN = "test_failure_plan"
    HIGH_STAKES = "high_stakes"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    TOOL_OUTPUT_TOO_LARGE = "tool_output_too_large"
