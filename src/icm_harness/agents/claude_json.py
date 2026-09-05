"""Shared parsing for the `claude -p --output-format json` envelope.

Both the stage agent (`claude_cli`) and the pre-round intake call
(`icm_harness.intake`) drive the `claude` CLI in headless JSON mode and face
the same two problems: the CLI wraps the model's text in a run envelope, and it
has no `--output-schema` so the inner payload can arrive fenced or prefaced.
This module owns that handling once; callers pass the exception type they want
raised so error surfaces stay meaningful in each context.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

# The `claude -p --output-format json` envelope carries the model's final text
# in `result`, alongside `is_error` / `subtype` run metadata.
ENVELOPE_RESULT_KEY = "result"


def unwrap_envelope(stdout: str, *, error: type[Exception] = ValueError) -> str:
    """Return the model's final text from the CLI's JSON envelope.

    Raises `error` when the CLI reported a failure, when the envelope is
    unparseable, or when it carries no textual result.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise error(
            "claude CLI returned a non-JSON envelope: " + (stdout[-2000:] or "<empty>")
        ) from exc
    if not isinstance(envelope, Mapping):
        raise error("claude CLI envelope was not a JSON object")
    if envelope.get("is_error") or envelope.get("subtype") not in (None, "success"):
        detail = str(envelope.get(ENVELOPE_RESULT_KEY) or envelope.get("subtype") or "error")
        raise error("claude CLI reported an error: " + detail[-2000:])
    result = envelope.get(ENVELOPE_RESULT_KEY)
    if not isinstance(result, str) or not result.strip():
        raise error("claude CLI envelope carried no textual result")
    return result


def extract_json(text: str) -> str:
    """Recover a JSON object from the model's final text.

    Strips a Markdown code fence if present, else takes the first balanced
    `{...}` span. The model is instructed to emit bare JSON; this only salvages
    the common fence/prose slips rather than trusting them.
    """
    body = text.strip()
    if body.startswith("```"):
        fence_end = body.rfind("```")
        inner = body[3:fence_end] if fence_end > 3 else body[3:]
        if inner.lstrip().lower().startswith("json"):
            inner = inner.lstrip()[4:]
        body = inner.strip()
    if body.startswith("{") and body.endswith("}"):
        return body
    start = body.find("{")
    end = body.rfind("}")
    if start != -1 and end > start:
        return body[start : end + 1]
    return body
