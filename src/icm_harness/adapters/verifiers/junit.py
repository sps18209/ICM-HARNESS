"""JUnit identity verifier; native framework phases require a native adapter."""

import xml.etree.ElementTree as ET

from icm_harness.kernel.test_evidence import compare_collection
from icm_harness.kernel.verification import Check


def evaluate_junit(source: bytes, check: Check) -> dict:
    source = source.decode("utf-8-sig")
    if "<!DOCTYPE" in source or "<!ENTITY" in source:
        raise ValueError("JUnit DTDs and entities are not supported")
    root = ET.fromstring(source)
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("expected JUnit testsuite/testsuites")
    cases = list(root.iter("testcase"))
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    identities = []
    skipped_ids = []
    for case in cases:
        if not case.get("name"):
            raise ValueError("JUnit testcase requires a stable name")
        identity = case.get("classname", "") + "::" + case.get("name")
        identities.append(identity)
        if case.find("skipped") is not None:
            skipped_ids.append(identity)
    identity_errors = compare_collection(check.expected_tests, identities)
    identity_errors += [
        f"unexpected skip: {item}" for item in skipped_ids if item not in check.optional_skips
    ]
    # Suite-level errors must not disappear merely because testcase nodes are absent.
    declared_errors = sum(int(suite.get("errors", "0")) for suite in root.iter("testsuite"))
    declared_failures = sum(int(s.get("failures", "0")) for s in root.iter("testsuite"))
    passed = bool(cases) and not (failures or errors or declared_errors or declared_failures)
    passed = passed and not identity_errors and skipped < len(cases)
    return {
        "passed": passed,
        "total": len(cases),
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "identity_errors": identity_errors,
        "optional_skips": [
            {"id": item, "reason": check.optional_skips[item]}
            for item in skipped_ids
            if item in check.optional_skips
        ],
    }


class JUnitVerifier:
    def evaluate(self, check: Check, source: bytes) -> dict:
        try:
            return evaluate_junit(source, check)
        except ET.ParseError as exc:
            raise ValueError(f"malformed JUnit report: {exc}") from exc
