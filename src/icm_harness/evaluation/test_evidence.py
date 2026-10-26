"""Deterministic test identity and phase checks; reports are not a sandbox."""

from __future__ import annotations

from collections import Counter


def compare_collection(expected: tuple[str, ...], observed: list[str]) -> list[str]:
    if not isinstance(observed, list) or any(not isinstance(x, str) or not x for x in observed):
        raise ValueError("invalid collected test identities")
    errors = [f"missing required test: {item}" for item in sorted(set(expected) - set(observed))]
    errors += [f"duplicate test identity: {item}" for item, n in Counter(observed).items() if n > 1]
    return errors


def validate_outcomes(expected: tuple[str, ...], optional: dict[str, str], data: object) -> dict:
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or not isinstance(data.get("events"), list)
        or type(data.get("exit_code")) is not int
        or not isinstance(data.get("collection_errors"), list)
        or any(not isinstance(x, str) for x in data["collection_errors"])
    ):
        raise ValueError("invalid pytest event report")
    collected = data.get("collected")
    errors = compare_collection(expected, collected)
    deselected = data.get("deselected")
    if not isinstance(deselected, list) or any(not isinstance(x, str) for x in deselected):
        raise ValueError("invalid deselected identities")
    errors += [f"deselected required test: {x}" for x in deselected if x in expected]
    if data["exit_code"] != 0 or data.get("collection_errors"):
        errors.append("pytest session or collection failed")
    phases: dict[str, dict[str, dict]] = {}
    for event in data["events"]:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("nodeid"), str)
            or event.get("when") not in {"setup", "call", "teardown"}
            or event.get("outcome") not in {"passed", "failed", "skipped"}
            or type(event.get("wasxfail")) is not bool
        ):
            raise ValueError("invalid pytest phase event")
        nodeid, when = event["nodeid"], event["when"]
        if nodeid not in collected:
            errors.append(f"event for uncollected test: {nodeid}")
        test = phases.setdefault(nodeid, {})
        if when in test:
            errors.append(f"duplicate phase: {nodeid} {when}")
        test[when] = event
        if event["outcome"] == "failed" or event["wasxfail"]:
            errors.append(f"failed or expected-failure outcome: {nodeid} {when}")
        if event["outcome"] == "skipped" and (nodeid not in optional or when == "teardown"):
            errors.append(f"unexpected skip: {nodeid} {when}")
    skipped = []
    for nodeid in collected:
        test = phases.get(nodeid, {})
        setup = test.get("setup", {}).get("outcome")
        is_optional_skip = nodeid in optional and any(
            x["outcome"] == "skipped" for x in test.values()
        )
        required_phases = {"setup", "teardown"} if setup == "skipped" else {
            "setup", "call", "teardown"
        }
        if set(test) != required_phases:
            errors.append(f"missing or unexpected execution phases: {nodeid}")
        if is_optional_skip:
            skipped.append({"id": nodeid, "reason": optional[nodeid]})
        elif any(x["outcome"] != "passed" for x in test.values()):
            errors.append(f"test did not pass: {nodeid}")
    if not collected or len(skipped) == len(collected):
        errors.append("empty or all-skipped test run")
    return {
        "passed": not errors,
        "total": len(collected),
        "skipped": len(skipped),
        "optional_skips": skipped,
        "errors": errors,
    }
