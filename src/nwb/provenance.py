"""Read the generator declared in an image's C2PA content credentials (e.g. OpenAI's
"ChatGPT · gpt-image" or Google's "Created by Google Generative AI") without a C2PA library.

C2PA manifests are CBOR inside the file, so this looks for the CBOR-encoded keys "name", "version",
and "description" and reads the text value after each. It reports what the vendor declares; it does
not verify the signature.
"""

import re
import functools
import subprocess
from datetime import datetime, timezone
from importlib.metadata import version

from nwb.config import find_root
from pathlib import Path


def _cbor_text(data: bytes, i: int) -> tuple[str | None, int]:
    """Decode a CBOR text string starting at data[i]; (None, i) if there is none."""
    if i >= len(data):
        return None, i
    head = data[i]
    if 0x60 <= head <= 0x77:
        n, j = head - 0x60, i + 1
    elif head == 0x78 and i + 1 < len(data):
        n, j = data[i + 1], i + 2
    elif head == 0x79 and i + 2 < len(data):
        n, j = int.from_bytes(data[i + 1:i + 3], "big"), i + 3
    else:
        return None, i
    if j + n > len(data):
        return None, i
    try:
        return data[j:j + n].decode("utf-8"), j + n
    except UnicodeDecodeError:
        return None, i


def c2pa_summary(path: Path) -> dict | None:
    """{"generators": ["ChatGPT gpt-image", ...], "actions": ["Created by ...", ...]}, or None when the
    image has no C2PA manifest."""
    data = Path(path).read_bytes()
    if b"c2pa" not in data:
        return None
    generators, actions = [], []
    for m in re.finditer(rb"\x64name", data):
        name, j = _cbor_text(data, m.end())
        if name and data[j:j + 8] == b"\x67version":
            version, _ = _cbor_text(data, j + 8)
            entry = f"{name} {version}".strip() if version else name
            if entry not in generators:
                generators.append(entry)
    for m in re.finditer(rb"\x6bdescription", data):
        text, _ = _cbor_text(data, m.end())
        if text and text not in actions:
            actions.append(text)
    return {"generators": generators, "actions": actions}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@functools.cache
def collection_identity() -> dict:
    """Freeze revision once per collector process, including collection-relevant local changes."""
    root = find_root()
    try:
        revision = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain", "--", "bench/", "src/",
                                         "config/", "models.toml"], cwd=root, text=True).strip()
        revision += "+dirty" if dirty else ""
    except (OSError, subprocess.CalledProcessError):
        revision = "unknown"
    return {"revision": revision, "nwb_version": version("nai-wai-bench")}
