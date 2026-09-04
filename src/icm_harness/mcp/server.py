from __future__ import annotations

import anyio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from icm_harness.application import HarnessApplication
from icm_harness.kernel.contracts import TaskIntent, TaskProfile

SERVER_INFO = {"name": "icm-harness", "version": "0.1.0"}
PROTOCOL_VERSION = "2024-11-05"


def _round_id(app: HarnessApplication, value: str | None) -> str:
    if value:
        return value
    current = app.current_round()
    if current is not None:
        return current.round_id
    recent = app.list_rounds(limit=1)
    if recent:
        return recent[0].round_id
    raise ValueError("no rounds exist; create one or pass a round_id")


def _profile(arguments: dict[str, Any]) -> TaskProfile:
    return TaskProfile(
        objective=str(arguments["objective"]).strip(),
        intent=TaskIntent(arguments.get("intent", "auto")),
        specification_clarity=float(arguments.get("clarity", 0.5)),
        epistemic_uncertainty=float(arguments.get("uncertainty", 0.5)),
        stakes=float(arguments.get("stakes", 0.5)),
        reversibility=float(arguments.get("reversibility", 0.5)),
        production_change_required=bool(arguments.get("production_change", False)),
        code_intensity=float(arguments.get("code_intensity", 0.0)),
        research_intensity=float(arguments.get("research_intensity", 0.0)),
        tool_intensity=float(arguments.get("tool_intensity", 0.0)),
        privacy_restricted=bool(arguments.get("privacy_restricted", False)),
        budget_usd=(
            float(arguments["budget_usd"])
            if arguments.get("budget_usd") is not None
            else None
        ),
    )


def _json_result(value: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, default=str, sort_keys=True)}],
        "structuredContent": value,
    }


def _tool_definitions() -> list[dict[str, Any]]:
    round_id = {
        "type": "string",
        "description": "Round identifier. Defaults to the current or most recent round.",
    }
    return [
        {
            "name": "icm_create_round",
            "description": "Create an ICM round for an objective without running it.",
            "inputSchema": {
                "type": "object",
                "required": ["objective"],
                "properties": {
                    "objective": {"type": "string"},
                    "intent": {
                        "type": "string",
                        "enum": ["auto", "build", "investigate", "decide", "review", "quick"],
                    },
                    "dry_run": {"type": "boolean", "default": False},
                    "production_change": {"type": "boolean", "default": False},
                    "clarity": {"type": "number", "minimum": 0, "maximum": 1},
                    "uncertainty": {"type": "number", "minimum": 0, "maximum": 1},
                    "stakes": {"type": "number", "minimum": 0, "maximum": 1},
                    "reversibility": {"type": "number", "minimum": 0, "maximum": 1},
                },
            },
        },
        {
            "name": "icm_run_round",
            "description": (
                "Run or resume an ICM round until it closes, blocks, fails, or awaits approval."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "round_id": round_id,
                    "dry_run": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "icm_list_rounds",
            "description": "List recent ICM rounds and their statuses.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
            },
        },
        {
            "name": "icm_get_round",
            "description": "Get a round, its events, artifacts, and worktree diff.",
            "inputSchema": {"type": "object", "properties": {"round_id": round_id}},
        },
        {
            "name": "icm_approve_gate",
            "description": "Approve the active human gate for a waiting round.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "round_id": round_id,
                    "run": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "icm_cancel_round",
            "description": "Request cancellation of an ICM round.",
            "inputSchema": {"type": "object", "properties": {"round_id": round_id}},
        },
        {
            "name": "icm_retry_round",
            "description": "Retry a failed, blocked, or cancelled round.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "round_id": round_id,
                    "run": {"type": "boolean", "default": False},
                    "dry_run": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "icm_promote_round",
            "description": "Promote a closed round's isolated worktree into the base branch.",
            "inputSchema": {"type": "object", "properties": {"round_id": round_id}},
        },
        {
            "name": "icm_events",
            "description": "Read the append-only event trail for a round.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "round_id": round_id,
                    "after": {"type": "integer", "minimum": 0},
                },
            },
        },
        {
            "name": "icm_artifacts",
            "description": "List artifacts for a round, or read one artifact by numeric id.",
            "inputSchema": {
                "type": "object",
                "properties": {"round_id": round_id, "artifact_id": {"type": "integer"}},
            },
        },
        {
            "name": "icm_diff",
            "description": "Read the isolated worktree diff for a round.",
            "inputSchema": {"type": "object", "properties": {"round_id": round_id}},
        },
    ]


def call_tool(root: Path, name: str, arguments: dict[str, Any]) -> Any:
    dry_run = bool(arguments.get("dry_run", False))
    app = HarnessApplication(root, dry_run=dry_run)
    if name == "icm_create_round":
        if not str(arguments.get("objective", "")).strip():
            raise ValueError("objective is required")
        return app.round_payload(app.create_round(_profile(arguments)))
    if name == "icm_run_round":
        round_id = _round_id(app, arguments.get("round_id"))
        return app.round_payload(anyio.run(app.run_round, round_id))
    if name == "icm_list_rounds":
        limit = int(arguments.get("limit", 100))
        return [app.round_payload(record) for record in app.list_rounds(limit=limit)]
    if name == "icm_get_round":
        round_id = _round_id(app, arguments.get("round_id"))
        record = app.get_round(round_id)
        payload = app.round_payload(record)
        payload["events"] = [asdict(event) for event in app.events(round_id)]
        payload["artifacts"] = [asdict(item) for item in app.list_artifacts(round_id)]
        payload["workspace_diff"] = app.diff_round(round_id)[:100_000]
        return payload
    if name == "icm_approve_gate":
        record = app.approve_round(_round_id(app, arguments.get("round_id")))
        if arguments.get("run"):
            record = anyio.run(app.run_round, record.round_id)
        return app.round_payload(record)
    if name == "icm_cancel_round":
        return app.round_payload(app.cancel_round(_round_id(app, arguments.get("round_id"))))
    if name == "icm_retry_round":
        record = app.retry_round(_round_id(app, arguments.get("round_id")))
        if arguments.get("run"):
            record = anyio.run(app.run_round, record.round_id)
        return app.round_payload(record)
    if name == "icm_promote_round":
        return app.round_payload(app.promote_round(_round_id(app, arguments.get("round_id"))))
    if name == "icm_events":
        round_id = _round_id(app, arguments.get("round_id"))
        return [
            asdict(event)
            for event in app.events(round_id, after_id=int(arguments.get("after", 0)))
        ]
    if name == "icm_artifacts":
        if arguments.get("artifact_id") is not None:
            record, content = app.read_artifact(int(arguments["artifact_id"]))
            payload = asdict(record)
            payload["content"] = content
            return payload
        round_id = _round_id(app, arguments.get("round_id"))
        return [asdict(item) for item in app.list_artifacts(round_id)]
    if name == "icm_diff":
        round_id = _round_id(app, arguments.get("round_id"))
        return {"round_id": round_id, "content": app.diff_round(round_id)}
    raise ValueError(f"unknown tool: {name}")


def handle_request(root: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_definitions()}}
    if method == "tools/call":
        params = request.get("params") or {}
        try:
            result = call_tool(root, str(params.get("name", "")), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": request_id, "result": _json_result(result)}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "isError": True,
                    **_json_result({"error": f"{type(exc).__name__}: {exc}"}),
                },
            }
    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> None:
    root = Path.cwd().resolve()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = handle_request(root, request)
        except (json.JSONDecodeError, TypeError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
        if response is not None:
            print(json.dumps(response, default=str, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
