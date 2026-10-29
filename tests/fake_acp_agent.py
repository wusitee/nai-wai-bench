"""Minimal ACP agent used by test_backends.py.

On each prompt it announces a tool call, asks the client for permission, optionally returns the
same inline image twice (when the prompt contains IMAGE), and replies with the selected model and the
permission decision it received.
"""

import base64
import json
import os
from pathlib import Path
import sys

PNG_1X1 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
model = "a"
effort = "low"


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def update(update):
    send({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "s1", "update": update}})


def config_options():
    return [{"id": "model", "category": "model", "type": "select", "currentValue": model,
             "options": [{"group": "g", "options": [{"value": "a"}, {"value": "b"}]}]},
            {"id": "thinking", "category": "thought_level", "type": "select", "currentValue": effort,
             "options": [{"value": "low"}, {"value": "high"}]}]


for line in sys.stdin:
    msg = json.loads(line)
    method, rid, params = msg.get("method"), msg.get("id"), msg.get("params", {})
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": 1, "agentCapabilities": {"promptCapabilities": {"image": True}}}})
    elif method == "session/new":
        update({"sessionUpdate": "available_commands_update", "availableCommands": [
            {"name": "usage", "description": "Show session token usage"}]})
        send({"jsonrpc": "2.0", "id": rid, "result": {"sessionId": "s1", "configOptions": config_options()}})
    elif method == "session/set_config_option":
        if params["configId"] == "model":
            model = params["value"]
        elif not os.environ.get("FAKE_IGNORE_EFFORT"):
            effort = params["value"]
        send({"jsonrpc": "2.0", "id": rid, "result": {"configOptions": config_options()}})
    elif method == "session/prompt":
        if params["prompt"] == [{"type": "text", "text": "/usage"}]:
            text = ("changed format" if os.environ.get("FAKE_USAGE_FORMAT") else
                    "Context: 30 / 1000 tokens (3%)\nSession total: 20 input, 10 output")
            update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}})
            send({"jsonrpc": "2.0", "id": rid, "result": {"stopReason": "end_turn"}})
            continue
        for i, block in enumerate(params["prompt"]):
            if block["type"] == "image":
                # A copied input in the output directory must not be collected as a generated image.
                Path(f"copy-{i}.png").write_bytes(base64.b64decode(block["data"]))
        text = "".join(b.get("text", "") for b in params["prompt"])
        update({"sessionUpdate": "tool_call", "toolCallId": "t1", "title": "web_search", "kind": "fetch",
                "status": "pending"})
        send({"jsonrpc": "2.0", "id": 900, "method": "session/request_permission", "params": {
            "sessionId": "s1", "toolCall": {"toolCallId": "t1", "title": "web_search"},
            "options": [{"optionId": "yes", "name": "Allow", "kind": "allow_once"},
                        {"optionId": "no", "name": "Reject", "kind": "reject_once"}]}})
        decision = json.loads(sys.stdin.readline())["result"]["outcome"].get("optionId")
        if "IMAGE" in text and decision == "yes":
            image = {"type": "image", "mimeType": "image/png", "data": PNG_1X1}
            update({"sessionUpdate": "tool_call_update", "toolCallId": "t1", "status": "completed",
                    "content": [{"type": "content", "content": image}]})
            update({"sessionUpdate": "agent_message_chunk", "content": image})  # same image again
        update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": (json.dumps({"cwd": os.getcwd(), "blocks": params["prompt"]}) if "INSPECT" in text else f"model={model} ")}})
        update({"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": ("" if "INSPECT" in text else f"permission={decision}")}})
        result = {"stopReason": "end_turn"}
        if not os.environ.get("FAKE_NO_USAGE"):
            result["usage"] = {"inputTokens": 20, "outputTokens": 10, "thoughtTokens": 4, "cachedReadTokens": 3}
        send({"jsonrpc": "2.0", "id": rid, "result": result})
    elif rid is not None:
        send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
