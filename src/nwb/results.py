"""Git-ready portable result snapshots, separate from resumable working runs."""

import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath

from nwb import __version__, bundle
from nwb.config import Bench, SUITES, validate_run_suite
from nwb.util import read_json, write_bytes, write_json

METADATA = "snapshot.json"


def directory(root: Path, suite: str, run_dir: Path) -> Path:
    if suite not in SUITES or run_dir.resolve().parent != (root / "runs").resolve():
        raise ValueError("synced runs must be direct children of runs/; use --no-sync for other working paths")
    return root / "results" / suite / run_dir.name


def _file(snapshot: Path, name: str) -> Path:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts or name == METADATA:
        raise ValueError(f"invalid result snapshot path: {name!r}")
    target = snapshot / path
    if not target.resolve().is_relative_to(snapshot.resolve()):
        raise ValueError(f"result snapshot path leaves its directory: {name!r}")
    return target


def _metadata(snapshot: Path, suite: str, run: str) -> dict:
    meta = read_json(snapshot / METADATA)
    if (meta.get("format") != 1 or meta.get("suite") != suite or meta.get("run") != run
            or not isinstance(meta.get("files"), dict)):
        raise ValueError(f"invalid result snapshot metadata: {snapshot / METADATA}")
    for name, digest in meta["files"].items():
        _file(snapshot, name)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"invalid checksum for snapshot file {name!r}")
    return meta


def sync(root: Path, bench: Bench, run_dir: Path, *, judges: set[str] | None = None,
         scores: dict | None = None) -> Path:
    snapshot = directory(root, bench.suite, run_dir)
    validate_run_suite(run_dir, bench.suite)
    prepared = bundle.prepare(run_dir, bench, judges=judges, scores=scores)
    previous = _metadata(snapshot, bench.suite, run_dir.name) if (snapshot / METADATA).is_file() else {"files": {}}
    for name, data in prepared.files.items():
        path = _file(snapshot, name)
        if not path.is_file() or path.read_bytes() != data:
            write_bytes(path, data)
    for name in previous["files"].keys() - prepared.files.keys():
        _file(snapshot, name).unlink(missing_ok=True)
    meta = {"format": 1, "nwb_version": __version__, "suite": bench.suite, "run": run_dir.name,
            "input_sha256": prepared.input_sha256, "judges": sorted(judges) if judges is not None else None,
            "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(prepared.files.items())}}
    if not (snapshot / METADATA).is_file() or read_json(snapshot / METADATA) != meta:
        write_json(snapshot / METADATA, meta)
    return snapshot


def restore(root: Path, suite: str, run_dir: Path) -> Path:
    snapshot = directory(root, suite, run_dir)
    if run_dir.exists():
        raise ValueError(f"working run already exists: {run_dir}; restore into a fresh working directory")
    if not (snapshot / METADATA).is_file():
        raise FileNotFoundError(f"saved results not found: {snapshot}")
    meta = _metadata(snapshot, suite, run_dir.name)
    files = {}
    for name, digest in meta["files"].items():
        data = _file(snapshot, name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"saved result checksum mismatch: {snapshot / name}")
        files[name] = data
    validate_run_suite(snapshot, suite)
    for name, data in files.items():
        write_bytes(_file(run_dir, name), data)
    return run_dir


def _merge_files(source: Path) -> dict[str, bytes]:
    """Read a run's result files, converting legacy mtime judgment identity to content identity."""
    files = {path.relative_to(source).as_posix(): path.read_bytes()
             for track in ("understanding", "imagegen", "judgments") for path in sorted((source / track).rglob("*"))
             if path.is_file() and path.suffix.lower() in bundle.RESULT_IMAGE_SUFFIXES | {".json"}}
    for name, data in files.items():
        judgment = json.loads(data) if name.startswith("judgments/") and name.endswith(".json") else {}
        if "target_mtime" in judgment and "target_sha256" not in judgment:
            # Merged copies get new mtimes; check freshness against this source and keep stale verdicts stale.
            target = source / judgment["target"]
            current = target.is_file() and target.stat().st_mtime == judgment.pop("target_mtime")
            judgment["target_sha256"] = (hashlib.sha256(target.read_bytes()).hexdigest() if current
                                         else "stale-before-merge")
            files[name] = json.dumps(judgment, ensure_ascii=False, indent=2).encode()
    return files


def merge(root: Path, suite: str, run_dir: Path, sources: list[Path]) -> Path:
    """Combine working runs into a fresh run; a file present in several sources must be identical."""
    if run_dir.exists():
        raise ValueError(f"working run already exists: {run_dir}; merge into a fresh run")
    if not sources:
        raise ValueError("merge needs at least one source run")
    selected, origin, log = {}, {}, []
    for source in sources:
        snapshot = directory(root, suite, source)
        if not source.exists() and (snapshot / METADATA).is_file():
            restore(root, suite, source)
        if not source.is_dir():
            raise FileNotFoundError(f"run not found: {source}")
        validate_run_suite(source, suite)
        for name, data in _merge_files(source).items():
            if selected.setdefault(name, data) != data:
                raise ValueError(f"runs {origin[name]!r} and {source.name!r} disagree on {name}")
            origin.setdefault(name, source.name)
        if (source / "collection.jsonl").is_file():
            text = (source / "collection.jsonl").read_text(encoding="utf-8")
            lines = [line for line in text.splitlines() if line.strip()]
            for line in lines:
                json.loads(line)
            log += lines
    try:
        run_dir.mkdir(parents=True)  # claim the target, so cleanup never removes another merge's run
    except FileExistsError:
        raise ValueError(f"working run already exists: {run_dir}; merge into a fresh run") from None
    try:
        for name, data in selected.items():
            write_bytes(run_dir / name, data)
        if log:
            write_bytes(run_dir / "collection.jsonl", "".join(f"{line}\n" for line in log).encode())
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise
    return run_dir
