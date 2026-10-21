"""Backends drive locally installed agent CLIs, so runs use existing logins instead of API keys, or call
OpenAI-compatible APIs directly.

Every call runs in a fresh, empty temporary working directory so agents never pick up this
repository's AGENTS.md / CLAUDE.md or any other project context.
"""

from dataclasses import dataclass, field
from pathlib import Path

from nwb.config import ModelSpec


class BackendError(RuntimeError):
    pass


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
