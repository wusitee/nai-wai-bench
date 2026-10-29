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
    write_bytes(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))


def write_bytes(path: Path, data: bytes) -> None:
    """Replace a result atomically; failed writes leave no temporary file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # The .part suffix keeps an interrupted write from matching the *.json result globs.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_json(text: str) -> dict:
    """Return the JSON object in a model reply: the whole reply if it is one, otherwise the last
    top-level object in it, fenced or not (judges reason first and end with their verdict)."""
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
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
