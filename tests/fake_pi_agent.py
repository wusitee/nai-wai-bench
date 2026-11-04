"""Minimal `pi --mode rpc` agent used by test_backends.py.

It reports the requested model and thinking level, unless FAKE_PI_* variables make it fall back, clamp, or
fail like pi does, and answers each prompt with JSON describing what it received. FAKE_PI_RATE_LIMITS names a
file counting the prompts, across processes, still to be refused with a provider rate-limit error.
"""

import json
import os
import sys

args = sys.argv[1:]
provider, _, model_id = os.environ.get("FAKE_PI_RESOLVED", args[args.index("--model") + 1]).partition("/")
model = {"provider": provider, "id": model_id,
         "input": ["text"] if os.environ.get("FAKE_PI_TEXT_ONLY") else ["text", "image"]}
thinking = os.environ.get("FAKE_PI_CLAMP") or (args[args.index("--thinking") + 1] if "--thinking" in args else "off")
auto_retry = True


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    command = json.loads(line)
    reply = {"id": command.get("id"), "type": "response", "command": command["type"], "success": True}
    if command["type"] == "set_auto_retry":
        auto_retry = command["enabled"]
        send(reply)
    elif command["type"] == "get_state":
        send({**reply, "data": {"model": model, "thinkingLevel": thinking}})
    elif command["type"] == "prompt":
        send(reply)
        received = {"cwd": os.getcwd(), "argv": args, "auto_retry": auto_retry, "images": command.get("images", [])}
        error = os.environ.get("FAKE_PI_ERROR")
        if limits := os.environ.get("FAKE_PI_RATE_LIMITS"):
            left = int(open(limits).read())
            if left:
                open(limits, "w").write(str(left - 1))
                error = '429: {"code":"MODEL_CALL_FAILED","data":{"retryAfterSeconds":3}}'
        message = {"role": "assistant", "provider": provider, "model": model_id,
                   "content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": json.dumps(received)}],
                   "usage": {"input": 10, "output": 5, "cacheRead": 20, "cacheWrite": 30, "reasoning": 2, "totalTokens": 65,
                             "cost": {"total": 0.25}},
                   "stopReason": "error" if error else "stop", **({"errorMessage": error} if error else {})}
        send({"type": "message_end", "message": message})
        send({"type": "agent_end", "messages": [{"role": "user", "content": command["message"]}, message]})
