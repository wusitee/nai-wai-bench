"""Backends drive locally installed agent CLIs, so runs use existing logins instead of API keys, or call
OpenAI-compatible APIs directly.

Every call runs in a fresh, empty temporary working directory so agents never pick up this
repository's AGENTS.md / CLAUDE.md or any other project context.
"""

import functools
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from nwb.config import ModelSpec


class BackendError(RuntimeError):
    pass


class ProviderRefusal(BackendError):
    """The provider's safety system rejected the request or its output. This is a model outcome, not an
    infrastructure error: it is recorded and scored instead of retried."""

    def __init__(self, message: str, meta: dict):
        super().__init__(message)
        self.meta = meta


@dataclass
class Request:
    prompt: str
    images: list[Path] = field(default_factory=list)
    # When set, the backend generates an image for `prompt` and saves it into this directory.
    image_out: Path | None = None


@dataclass
class Response:
    """meta always includes "tools_used": the tool calls the agent made (empty when it used none)."""
    text: str = ""
    images: list[Path] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


def neutral_inputs(run):
    """Stage every attachment at call time, including judges' generated-image inputs."""
    @functools.wraps(run)
    def staged(self, req: Request) -> Response:
        with tempfile.TemporaryDirectory(prefix="nwb-input-") as directory:
            images = []
            for i, source in enumerate(req.images, 1):
                target = Path(directory) / f"image-{i}{source.suffix.lower()}"
                shutil.copyfile(source, target)
                images.append(target)
            return run(self, Request(req.prompt, images, req.image_out))
    return staged


def tokens(backend: str, usage: dict | None) -> dict:
    """Normalize client telemetry; absent counters remain unknown, including partial usage."""
    u = usage or {}
    result = dict.fromkeys(("input", "cached_input", "cache_write", "output", "reasoning"))
    if backend == "codex":
        # Output already includes reasoning; total_tokens may be absent.
        result.update(input=u.get("input_tokens"), cached_input=u.get("cached_input_tokens"),
                      cache_write=u.get("cache_write_input_tokens"), output=u.get("output_tokens"),
                      reasoning=u.get("reasoning_output_tokens"))
    elif backend == "claude":
        counters = [u.get(k) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")]
        result.update(input=sum(counters) if all(v is not None for v in counters) else None,
                      cached_input=u.get("cache_read_input_tokens"), cache_write=u.get("cache_creation_input_tokens"),
                      output=u.get("output_tokens"), reasoning=u.get("reasoning_tokens"))
    elif backend == "openai":
        result.update(input=u.get("prompt_tokens"),
                      cached_input=(u.get("prompt_tokens_details") or {}).get("cached_tokens"),
                      output=u.get("completion_tokens"),
                      reasoning=(u.get("completion_tokens_details") or {}).get("reasoning_tokens"))
    elif backend == "acp":
        result.update(input=u.get("inputTokens"), cached_input=u.get("cachedReadTokens"),
                      cache_write=u.get("cachedWriteTokens"), output=u.get("outputTokens"),
                      reasoning=u.get("thoughtTokens"))
        # Some ACP adapters report uncached input. Add cache categories only when the
        # reported total demonstrates that they are additional, rather than subsets.
        if all(result[k] is not None for k in ("input", "output")):
            cache = (result["cached_input"] or 0) + (result["cache_write"] or 0)
            if u.get("totalTokens") == result["input"] + result["output"] + cache:
                result["input"] += cache
    return result


def get_backend(spec: ModelSpec):
    if spec.backend == "codex":
        from nwb.backends.codex import CodexBackend
        return CodexBackend(spec)
    if spec.backend == "claude":
        from nwb.backends.claude import ClaudeBackend
        return ClaudeBackend(spec)
    if spec.backend == "acp":
        from nwb.backends.acp import AcpBackend
        return AcpBackend(spec)
    if spec.backend == "openai":
        from nwb.backends.openai_compat import OpenAICompatBackend
        return OpenAICompatBackend(spec)
    raise ValueError(f"model {spec.name}: unknown backend {spec.backend!r}")


def run_cli(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a CLI through its executable on PATH and read its output as UTF-8; recorded command templates
    keep the bare name. Windows starts npm-installed CLIs only through the full path of their `.cmd` shim,
    and cmd.exe parses that command line again, so arguments it would reinterpret are refused."""
    command = [shutil.which(command[0]) or command[0], *command[1:]]
    if Path(command[0]).suffix.lower() in {".bat", ".cmd"}:
        if unsafe := next((arg for arg in command if set(arg) & set("%&|<>^")), None):
            raise BackendError(f"cannot pass {unsafe!r} safely through {Path(command[0]).name}; use paths "
                               "without % & | < > ^ (e.g. set TEMP) or a native executable")
    # Errors from a shim can use the console code page; decoding must not hide the exit status.
    return subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", **kwargs)


@functools.cache
def cli_version(command: str) -> str | None:
    """`<command> --version` output (first line), recorded with each result as the client version."""
    try:
        out = run_cli([command, "--version"], timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired, BackendError):
        return None
    return out.strip().splitlines()[0] if out.strip() else None


def audit_calls(sent: list[str | None], raw: list[str], prompt: str) -> dict:
    """Report how many image tool calls were made and whether each one's prompt argument (`sent`, None
    when it could not be read) equals `prompt` exactly, ignoring surrounding whitespace."""
    return {
        "image_gen_calls": len(sent),
        "verbatim": bool(sent) and all(isinstance(s, str) and s.strip() == prompt.strip() for s in sent),
        "sent": sent,
        "calls": [c[:2000] for c in raw],
    }


def image_instruction(prompt: str, with_reference: bool, tool: str, save_hint: str = "") -> str:
    """Wrap a benchmark prompt so an agent forwards it to its image tool untouched."""
    ref = ", using the attached image as the reference image" if with_reference else ""
    return (
        f"Call the {tool} tool exactly once{ref}. Pass this prompt to it verbatim, character for "
        f"character, with no additions, rewrites, or translation:\n\n{prompt}\n\n"
        f"Do not search the web, do not run shell commands, do not ask questions.{save_hint} "
        "After the tool returns, reply with the single word DONE."
    )
