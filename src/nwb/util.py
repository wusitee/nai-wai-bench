import json
import os
import re
import tempfile
from pathlib import Path

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}


def media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "image/png")


def write_json(path: Path, obj) -> None:
    """Write JSON atomically so interrupted runs never leave half-written results."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def extract_json(text: str) -> dict:
    """Return the JSON object in a model reply: the whole reply, the last fenced block, or the last
    top-level object embedded in prose (judges reason first and end with their verdict)."""
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    for m in reversed(list(_FENCE.finditer(text))):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    last, i = None, 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            last = obj
        i = end  # skip the nested objects of a parsed top-level one
    if last is None:
        raise ValueError("no JSON object found in reply")
    return last


def expand(value: str) -> str:
    """Expand ~ and ${VAR}; fail loudly on unset variables instead of passing them through."""
    out = os.path.expanduser(os.path.expandvars(value))
    missing = re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", out)
    if missing:
        raise RuntimeError(f"environment variable(s) not set: {', '.join(missing)}")
    return out
