"""Portable raw results, preserving judgment freshness across export and relocation."""

import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from nwb import CANARY, __version__, scoring
from nwb.config import Bench
from nwb.util import read_json

RESULT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif"}


@dataclass
class PreparedBundle:
    files: dict[str, bytes]
    input_sha256: str


def _sanitize(value):
    if isinstance(value, str):
        return value.replace(str(Path.home()), "~")
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    return value


def _json_bytes(value, indent=2):
    return (json.dumps(_sanitize(value), ensure_ascii=False, indent=indent) + "\n").encode()


def _export_inputs(run_dir: Path, bench: Bench) -> dict[str, bytes]:
    files = {}
    identities = {}
    records = {}
    for track in ("understanding", "imagegen"):
        for path in sorted((run_dir / track).rglob("*")):
            if not path.is_file() or path.suffix.lower() not in RESULT_IMAGE_SUFFIXES | {".json"}:
                continue
            name = path.relative_to(run_dir).as_posix()
            if path.suffix == ".json":
                records[name] = read_json(path)
                data = _json_bytes(records[name])
                identities[name] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime,
                                    hashlib.sha256(data).hexdigest())
            else:
                data = path.read_bytes()
            files[name] = data
    for path in sorted((run_dir / "judgments").rglob("*.json")):
        judgment = read_json(path)
        identity = identities.get(judgment.get("target"))
        if identity:
            original_hash, original_mtime, exported_hash = identity
            current = (judgment["target_sha256"] == original_hash if "target_sha256" in judgment
                       else judgment.get("target_mtime") == original_mtime)
            # Sanitization changes bytes and extraction loses mtimes. Preserve freshness, including stale verdicts.
            judgment["target_sha256"] = exported_hash if current else "stale-before-export"
            judgment.pop("target_mtime", None)
            original_prompt = scoring.judgment_prompt(bench, records[judgment["target"]])
            if original_prompt and judgment.get("judge_prompt") == hashlib.sha256(original_prompt.encode()).hexdigest()[:16]:
                exported_prompt = scoring.judgment_prompt(bench, _sanitize(records[judgment["target"]]))
                judgment["judge_prompt"] = hashlib.sha256(exported_prompt.encode()).hexdigest()[:16]
        files[path.relative_to(run_dir).as_posix()] = _json_bytes(judgment)
    manifest = run_dir / "collection.jsonl"
    if manifest.is_file():
        files["collection.jsonl"] = b"".join(_json_bytes(json.loads(line), indent=None)
                                             for line in manifest.read_text().splitlines() if line.strip())
    return files


def input_digest(run_dir: Path, bench: Bench) -> str:
    """Hash normalized raw inputs so moving or extracting a bundle preserves its release identity."""
    return _digest(_export_inputs(run_dir, bench))


def _digest(files: dict[str, bytes]) -> str:
    entries = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare(run_dir: Path, bench: Bench, *, judges: set[str] | None = None,
            scores: dict | None = None) -> PreparedBundle:
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run not found: {run_dir}")
    if scores is None:
        scores = scoring.aggregate(run_dir, bench.trait_weights, judges, bench=bench)
    files = _export_inputs(run_dir, bench)
    digest = _digest(files)
    files["scores.json"] = _json_bytes(scores)
    selection = "" if judges is None else f" --judges {','.join(sorted(judges))}" if judges else " --judges ''"
    files["BUNDLE-README.md"] = (
        f"# nai-wai-bench {__version__} results\n\nSuite: `{bench.suite}`. Run: `{run_dir.name}`.\n\n"
        f"{CANARY}\n\nTo re-score, use the matching benchmark source (software version {__version__}), "
        "restore these files into "
        f"`runs/{run_dir.name}/`, then run:\n\n"
        f"```sh\nuv run nwb report --run {run_dir.name} --suite {bench.suite}{selection}\n```\n\n"
        "Home-directory prefixes in JSON strings are replaced with `~`. Judgment target hashes refer to the "
        "sanitized exported records; legacy mtime identity is converted to content identity without making stale "
        "judgments current. Re-scoring uses the keys and rubric from the matching source version.\n"
    ).encode()
    return PreparedBundle(files, digest)


def export(run_dir: Path, bench: Bench, out: Path, *, judges: set[str] | None = None, scores: dict | None = None) -> Path:
    prepared = prepare(run_dir, bench, judges=judges, scores=scores)
    out.mkdir(parents=True, exist_ok=True)
    archive = out / f"nai-wai-bench-{__version__}-{bench.suite}-{run_dir.name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, data in sorted(prepared.files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, data)
    return archive
