"""Models through the pi coding agent's RPC mode (`pi --mode rpc`), using pi's own logins, API keys, and
custom providers. Tools, extensions, skills, prompt templates, context files, and automatic network activity
are disabled, and the coding-agent system prompt is replaced with a neutral one."""

import base64
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from nwb.backends import (BackendError, Request, Response, cli_command, cli_version, extra_env, neutral_inputs,
                          tokens)
from nwb.config import ModelSpec
from nwb.util import media_type

SYSTEM_PROMPT = "You are a helpful assistant."
ANSWERED = ("stop", "length")


def _client() -> str | None:
    version = cli_version("pi")  # e.g. "0.73.1"
    return f"pi {version}" if version else None


def _total(values) -> float | None:
    values = list(values)
    return sum(values) if values and all(isinstance(v, (int, float)) for v in values) else None


class PiBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.timeout = spec.options.get("timeout", 600)
        self.effort = spec.options.get("effort", "default")

    def command(self) -> list[str]:
        # --no-extensions also disables pi's built-in MCP support, so no MCP servers are started.
        cmd = [
            "pi", "--mode", "rpc", "--no-session", "--offline", "--no-tools", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-themes", "--no-context-files", "--system-prompt", SYSTEM_PROMPT,
            "--model", self.spec.model,
        ]
        if self.effort != "default":
            cmd += ["--thinking", self.effort]
        return cmd

    @neutral_inputs
    def run(self, req: Request) -> Response:
        if req.image_out is not None:
            raise BackendError("the pi backend cannot generate images")
        images = [{"type": "image", "data": base64.b64encode(Path(p).read_bytes()).decode(),
                   "mimeType": media_type(Path(p))} for p in req.images]
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="nwb-pi-") as cwd, \
                tempfile.TemporaryFile("w+", encoding="utf-8") as stderr:
            try:
                state, messages = self._session(cwd, stderr, req.prompt, images)
            except BackendError as e:
                stderr.seek(0)
                tail = stderr.read()[-600:].strip()
                raise BackendError(f"{e}{' | stderr: ' + tail if tail else ''}") from e
        replies = [m for m in messages if m.get("role") == "assistant"]
        if not replies:
            raise BackendError("pi returned no assistant message")
        last = replies[-1]
        if last.get("stopReason") not in ANSWERED:
            raise BackendError(f"pi {last.get('stopReason')}: {str(last.get('errorMessage', ''))[:800]}")
        # One assistant message without tools; counters are summed over the turn and stay unknown if missing.
        usages = [m.get("usage") or {} for m in replies]
        usage = {k: _total(u.get(k) for u in usages)
                 for k in ("input", "output", "cacheRead", "cacheWrite", "reasoning")}
        usage["cost"] = _total((u.get("cost") or {}).get("total") for u in usages)
        text = "".join(b.get("text", "") for b in last.get("content", []) if b.get("type") == "text")
        return Response(text=text, meta={
            "backend": "pi", "model": self.spec.model, "client": _client(),
            "seconds": round(time.monotonic() - started, 1), "stop_reason": last.get("stopReason"),
            "tools_used": [b.get("name") or "tool" for m in replies for b in m.get("content", [])
                           if b.get("type") == "toolCall"],
            "usage": usage, "tokens": tokens("pi", usage),
            "session_config": {"thinkingLevel": state.get("thinkingLevel")},
            "resolved_model": f"{last.get('provider')}/{last.get('responseModel') or last.get('model')}",
            # pi's estimate from its model registry's list prices, also for subscription logins.
            "cost_usd_reported": usage["cost"],
        })

    def _session(self, cwd: str, stderr, prompt: str, images: list[dict]) -> tuple[dict, list[dict]]:
        """Confirm the model and thinking level, then prompt once. Closing stdin ends pi, so it stays open
        until the agent finishes."""
        proc = subprocess.Popen(cli_command(self.command()), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=stderr, cwd=cwd, env={**os.environ, **extra_env(self.spec)}, text=True,
                                encoding="utf-8")
        lines = queue.Queue()

        def read():
            try:
                for line in proc.stdout:  # split on "\n" only: JSON strings may contain U+2028
                    lines.put(line)
            except (OSError, ValueError):
                pass  # pi was killed mid-read
            lines.put(None)

        threading.Thread(target=read, daemon=True).start()
        expired = threading.Event()
        # The watchdog bounds writes as well as waits: a large prompt (base64 images) blocks on a full pipe if
        # pi stops reading, and killing pi unblocks it.
        watchdog = threading.Timer(self.timeout, lambda: (expired.set(), proc.kill()))
        watchdog.start()

        def send(command: dict) -> None:
            try:
                proc.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
                proc.stdin.flush()
            except OSError:
                pass  # pi exited or was killed; reported by the next wait

        def wait(name: str) -> dict:
            """The successful response to command `name`, or the next event of type `name`."""
            while (line := lines.get()) is not None:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "response":
                    if not event.get("success"):
                        raise BackendError(f"pi {event.get('command')} failed: {event.get('error')}")
                    if event.get("id") == name:
                        return event.get("data") or {}
                elif event.get("type") == name:
                    return event
            raise BackendError(f"pi timed out after {self.timeout}s" if expired.is_set()
                               else f"pi exited while waiting for {name}")

        try:
            # pi emits agent_end before retrying a failed request; failed samples are retried on the next run.
            send({"id": "set_auto_retry", "type": "set_auto_retry", "enabled": False})
            wait("set_auto_retry")
            send({"id": "get_state", "type": "get_state"})
            state = wait("get_state")
            self._check(state, bool(images))
            send({"id": "prompt", "type": "prompt", "message": prompt, "images": images})
            return state, wait("agent_end").get("messages", [])
        finally:
            watchdog.cancel()
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _check(self, state: dict, has_images: bool) -> None:
        """pi falls back to another model and clamps unsupported thinking levels without failing."""
        model = state.get("model")
        if not model:
            raise BackendError(f"pi has no model {self.spec.model!r}; see `pi --list-models`")
        resolved = f"{model.get('provider')}/{model.get('id')}"
        if self.spec.model.lower() not in (str(model.get("id")).lower(), resolved.lower()):
            raise BackendError(f"pi selected {resolved}, not {self.spec.model}; use an exact provider/id")
        if self.effort != "default" and state.get("thinkingLevel") != self.effort:
            raise BackendError(f"pi did not confirm thinking level {self.effort!r} for {resolved} "
                               f"(session uses {state.get('thinkingLevel')!r})")
        if has_images and "image" not in model.get("input", []):
            raise BackendError(f"pi model {resolved} does not accept image input")
