import json

from icm_harness.mcp.server import handle_request


def test_initialize_and_list_tools(tmp_path):
    initialized = handle_request(
        tmp_path,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert initialized["result"]["capabilities"] == {"tools": {}}

    listed = handle_request(
        tmp_path,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"icm_create_round", "icm_run_round", "icm_diff"} <= names


def test_create_and_list_round(tmp_path):
    created = handle_request(
        tmp_path,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "icm_create_round",
                "arguments": {"objective": "test MCP", "dry_run": True},
            },
        },
    )
    payload = json.loads(created["result"]["content"][0]["text"])
    assert payload["objective"] == "test MCP"

    listed = handle_request(
        tmp_path,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "icm_list_rounds", "arguments": {}},
        },
    )
    rounds = json.loads(listed["result"]["content"][0]["text"])
    assert len(rounds) == 1
