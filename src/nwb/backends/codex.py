"""OpenAI models through `codex exec` (ChatGPT login). Image generation uses Codex's built-in
image_gen tool; the session rollout is checked to confirm the prompt was passed verbatim."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from nwb.backends import (BackendError, ProviderRefusal, Request, Response, audit_calls, cli_version,
                          executable, image_instruction, neutral_inputs, tokens)
from nwb.config import ModelSpec
from nwb.util import IMAGE_SUFFIXES

DISABLED_FEATURES = ("apps", "browser_use", "browser_use_external", "computer_use")
ISOLATED_FEATURES = ("shell_tool", "unified_exec", "multi_agent", "multi_agent_v2", "plugins",
                     "skill_search", "goals", "sleep_tool", "view_image", "collaboration_modes",
                     "default_mode_request_user_input")
TOOL_PROFILES = {"legacy-v1": (), "isolated-v1": ISOLATED_FEATURES}


def recorded_tool_profile(command: list[str]) -> str:
    disabled = {command[i + 1] for i, arg in enumerate(command[:-1]) if arg == "--disable"}
    baseline = set(DISABLED_FEATURES) | ({"image_generation"} if "image_generation" in disabled else set())
    if disabled == baseline | set(ISOLATED_FEATURES):
        return "isolated-v1"
    if disabled == baseline:
        return "legacy-v1"
    return "custom"


# The prompt argument of a code-mode call such as `tools.image_gen__imagegen({prompt: "..."})`.
_JS_PROMPT = re.compile(r"""(?<![\w$])["']?prompt["']?\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)""", re.S)


class CodexBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.timeout = spec.options.get("timeout", 600)
        self.home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()

    def command(self, images: list[Path], generate: bool) -> list[str]:
        profile = self.spec.options.get("tool_profile", "legacy-v1")
        if profile not in TOOL_PROFILES:
            raise ValueError(f"unknown Codex tool_profile {profile!r}; choose from {', '.join(TOOL_PROFILES)}")
        cmd = [
            "codex", "exec", "--json", "--skip-git-repo-check", "--ignore-user-config",
            "--sandbox", "read-only", "-c", 'web_search="disabled"', "--model", self.spec.model,
        ]
        # The apps connector carries its own web search; browser and computer use also reach the web.
        for feature in DISABLED_FEATURES + (() if generate else ("image_generation",)):
            cmd += ["--disable", feature]
        if (effort := self.spec.options.get("effort", self.spec.options.get("reasoning"))) and effort != "default":
            cmd += ["-c", f'model_reasoning_effort="{effort}"']
        if not generate:
            for feature in TOOL_PROFILES[profile]:
                cmd += ["--disable", feature]
        # --image takes multiple values, so it goes last and the prompt is sent on stdin.
        for img in images:
            cmd += ["--image", str(Path(img).resolve())]
        return cmd

    @neutral_inputs
    def run(self, req: Request) -> Response:
        gen = req.image_out is not None
        prompt = image_instruction(req.prompt, bool(req.images), "image_gen") if gen else req.prompt
        started = time.monotonic()
        command = self.command(req.images, gen)
        command[0] = executable(command[0])
        with tempfile.TemporaryDirectory(prefix="nwb-codex-") as cwd:
            try:
                proc = subprocess.run(command, input=prompt, capture_output=True,
                                      encoding="utf-8", cwd=cwd, timeout=self.timeout)
            except subprocess.TimeoutExpired as e:
                raise BackendError(f"codex timed out after {self.timeout}s") from e
        events = parse_events(proc.stdout)
        thread_id = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
        failures = [e for e in events if e.get("type") in ("turn.failed", "error")]
        if proc.returncode != 0 or failures or not thread_id:
            detail = json.dumps(failures[-1], ensure_ascii=False) if failures else proc.stderr.strip()[-800:]
            raise BackendError(f"codex exited {proc.returncode}: {detail}")

        items = [e["item"] for e in events if e.get("type") == "item.completed" and "item" in e]
        messages = [i.get("text", "") for i in items if i.get("type") == "agent_message"]
        meta = {
            "backend": "codex", "model": self.spec.model, "client": cli_version("codex"), "thread_id": thread_id,
            "seconds": round(time.monotonic() - started, 1),
            "tools_used": [i.get("type") for i in items if i.get("type") not in ("agent_message", "reasoning")],
            "usage": next((e.get("usage") for e in events if e.get("type") == "turn.completed"), None),
        }
        meta.update(tokens=tokens("codex", meta["usage"]), resolved_model=None, cost_usd_reported=None)
        resp = Response(text=messages[-1] if messages else "", meta=meta)
        if gen:
            resp.images = self._collect_images(thread_id, req.image_out, req.images)
            meta["audit"] = audit_rollout(self._rollout(thread_id), req.prompt)
            if not resp.images and meta["audit"].get("refused"):
                raise ProviderRefusal(f"image provider refused (thread {thread_id}): moderation_blocked", meta)
            if not resp.images:
                raise BackendError(f"codex produced no image (thread {thread_id}): {resp.text[:200]}")
        return resp

    def _collect_images(self, thread_id: str, out_dir: Path, inputs: list[Path]) -> list[Path]:
        src_dir = self.home / "generated_images" / thread_id
        if not src_dir.is_dir():
            return []
        out_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        excluded = {hashlib.sha256(p.read_bytes()).digest() for p in inputs}
        for src in sorted(p for p in src_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES):
            if hashlib.sha256(src.read_bytes()).digest() in excluded:
                continue
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            copied.append(dst)
        return copied

    def _rollout(self, thread_id: str) -> Path | None:
        return next(iter(self.home.glob(f"sessions/*/*/*/rollout-*-{thread_id}.jsonl")), None)


def parse_events(stdout: str) -> list[dict]:
    events = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def audit_rollout(rollout: Path | None, prompt: str) -> dict:
    """Report how many image_gen calls the agent made, whether `prompt` was passed verbatim, and whether
    the provider's safety system rejected a call."""
    if rollout is None:
        return {"rollout": None, "image_gen_calls": None, "verbatim": None}
    calls, sent, refused = [], [], False
    with open(rollout, encoding="utf-8") as f:
        for line in f:
            try:
                payload = json.loads(line).get("payload", {})
            except json.JSONDecodeError:
                continue
            if payload.get("type") in ("custom_tool_call_output", "function_call_output"):
                refused = refused or "moderation_blocked" in json.dumps(payload.get("output"))
                continue
            if payload.get("type") not in ("custom_tool_call", "function_call"):
                continue
            body = payload.get("input") or payload.get("arguments") or ""
            if "image_gen" in payload.get("name", "") or "image_gen" in body:
                calls.append(body)
                sent.append(call_prompt(body))
    return {"rollout": str(rollout), **audit_calls(sent, calls, prompt), "refused": refused}


def call_prompt(body: str) -> str | None:
    """The prompt argument of an image_gen call: from JSON arguments or a JavaScript string literal.
    None when it cannot be read statically (e.g. a variable or an interpolated template)."""
    try:
        args = json.loads(body)
        if isinstance(args, dict):
            return args.get("prompt") if isinstance(args.get("prompt"), str) else None
    except json.JSONDecodeError:
        pass
    m = _JS_PROMPT.search(body)
    if not m:
        return None
    literal = m.group(1)
    if literal[0] == '"':
        try:
            return json.loads(literal)
        except json.JSONDecodeError:
            return None
    if literal[0] == "`" and "${" in literal:
        return None
    return re.sub(r"\\(.)", lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)), literal[1:-1])
