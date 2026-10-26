"""Native pytest event verifier, independent of execution transport."""

import json

from icm_harness.kernel.test_evidence import validate_outcomes
from icm_harness.kernel.verification import Check


class PytestEventVerifier:
    def evaluate(self, check: Check, source: bytes) -> dict:
        return validate_outcomes(check.expected_tests, check.optional_skips, json.loads(source))
