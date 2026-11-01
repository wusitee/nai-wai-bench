"""Models through `claude -p`, with tools, MCP servers, settings, and the coding-agent system prompt all
disabled so the model answers from its own knowledge. Anthropic models use the Claude Code login; other
models use an Anthropic-compatible endpoint from the entry's `env` or a CC Switch provider."""

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from nwb.backends import BackendError, Request, Response, cli_version, extra_env, neutral_inputs, run_cli, tokens
from nwb.backends.cc_switch import claude_env
from nwb.config import ModelSpec
from nwb.util import media_type

SYSTEM_PROMPT = "You are a helpful assistant."


def _client() -> str | None:
    version = cli_version("claude")  # e.g. "2.1.306 (Claude Code)"
    return f"claude-code {version.split()[0]}" if version else None


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
        if (effort := self.spec.options.get("effort")) and effort != "default":
            cmd += ["--effort", effort]
        return cmd

    def configured_env(self) -> dict[str, str]:
        """The CC Switch provider's environment, overridden by the entry's `env` table."""
        env = claude_env(self.spec.options["cc_switch"]) if self.spec.options.get("cc_switch") else {}
        return env | extra_env(self.spec)

    @neutral_inputs
    def run(self, req: Request) -> Response:
        if req.image_out is not None:
            raise BackendError("the claude backend cannot generate images")
        configured = self.configured_env()
        custom = bool(configured.get("ANTHROPIC_BASE_URL"))
        if custom and not (configured.get("ANTHROPIC_AUTH_TOKEN") or configured.get("ANTHROPIC_API_KEY")):
            raise BackendError(f"model {self.spec.name}: its endpoint needs ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY; "
                               "otherwise Claude Code would send its own login there")
        # Inherited credentials and provider switches must not override the configured endpoint.
        provider_switches = {"CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"}
        env = {**{k: v for k, v in os.environ.items()
                  if not (custom and (k.startswith("ANTHROPIC_") or k == "CLAUDE_CODE_OAUTH_TOKEN"
                                      or k in provider_switches))},
               **configured}
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
                proc = run_cli(self.command(), input=message + "\n", cwd=cwd, env=env, timeout=self.timeout)
            except subprocess.TimeoutExpired as e:
                raise BackendError(f"claude timed out after {self.timeout}s") from e
        result = None
        for line in proc.stdout.splitlines():
            if line.startswith("{"):
                event = json.loads(line)
                if event.get("type") == "result":
                    result = event
        if proc.returncode != 0 or result is None or result.get("is_error"):
            detail = (result or {}).get("result") or proc.stderr.strip()[-800:]
            raise BackendError(f"claude exited {proc.returncode}: {detail}")
        # Claude Code also lists auxiliary models in modelUsage, sometimes first; the answer costs the most.
        usage_by_model = result.get("modelUsage") or {}
        # Claude Code's cost estimate uses Anthropic prices, which do not apply to other providers' models.
        cost = None if custom else result.get("total_cost_usd")
        return Response(text=result.get("result", ""), meta={
            "backend": "claude", "model": self.spec.model, "client": _client(),
            "seconds": round(time.monotonic() - started, 1),
            "tokens": tokens("claude", result.get("usage")),
            "resolved_model": max(usage_by_model, key=lambda m: usage_by_model[m].get("costUSD") or 0,
                                  default=None),
            "cost_usd_reported": cost, "tools_used": [], "cost_usd": cost, "usage": result.get("usage"),
        })


def endpoint(spec: ModelSpec) -> str | None:
    """Hostname of a configured Anthropic-compatible endpoint, for collection settings (never credentials)."""
    try:
        base = ClaudeBackend(spec).configured_env().get("ANTHROPIC_BASE_URL")
    except BackendError:
        return None  # Missing credentials are reported as a per-job backend error.
    return urlsplit(base).hostname if base else None
