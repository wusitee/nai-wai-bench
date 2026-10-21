"""Anthropic models through `claude -p` (Claude Code login), with tools, MCP servers, settings,
and the coding-agent system prompt all disabled so the model answers from its own knowledge."""

import base64
import json
import subprocess
import tempfile
import time
from pathlib import Path

from nwb.backends import BackendError, Request, Response
from nwb.config import ModelSpec
from nwb.util import media_type

SYSTEM_PROMPT = "You are a helpful assistant."


class ClaudeBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.timeout = spec.options.get("timeout", 600)

    def command(self) -> list[str]:
        cmd = [
            "claude", "-p", "--model", self.spec.model, "--tools", "", "--setting-sources", "",
            "--strict-mcp-config", "--no-session-persistence", "--system-prompt", SYSTEM_PROMPT,
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        ]
        if effort := self.spec.options.get("effort"):
            cmd += ["--effort", effort]
        return cmd

    def run(self, req: Request) -> Response:
        if req.image_out is not None:
            raise BackendError("the claude backend cannot generate images")
        content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type(Path(p)),
                                         "data": base64.b64encode(Path(p).read_bytes()).decode()}}
            for p in req.images
        ]
        content.append({"type": "text", "text": req.prompt})
        message = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="nwb-claude-") as cwd:
            try:
                proc = subprocess.run(self.command(), input=message + "\n", capture_output=True,
                                      text=True, cwd=cwd, timeout=self.timeout)
            except subprocess.TimeoutExpired as e:
                raise BackendError(f"claude timed out after {self.timeout}s") from e
        result = None
        for line in proc.stdout.splitlines():
            if line.startswith("{"):
                event = json.loads(line)
                if event.get("type") == "result":
                    result = event
        if result is None or result.get("is_error"):
            detail = (result or {}).get("result") or proc.stderr.strip()[-800:]
            raise BackendError(f"claude exited {proc.returncode}: {detail}")
        return Response(text=result.get("result", ""), meta={
            "backend": "claude", "model": self.spec.model,
            "seconds": round(time.monotonic() - started, 1),
            "tools_used": [], "cost_usd": result.get("total_cost_usd"), "usage": result.get("usage"),
        })
