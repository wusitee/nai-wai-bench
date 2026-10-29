"""Build a release offline from explicitly selected, content-pinned raw runs."""

import hashlib
import re
import tomllib
from pathlib import Path

from nwb import __version__, bundle, results, scoring, site
from nwb.config import SUITES, load_bench, load_models, validate_run_suite
from nwb.util import write_json


def load_manifest(path: Path) -> dict:
    with path.open("rb") as stream:
        manifest = tomllib.load(stream)
    if manifest.get("nwb_version") != __version__:
        raise ValueError(f"release requires nwb {manifest.get('nwb_version')!r}; installed version is {__version__}")
    suites = manifest.get("suites", {})
    if not isinstance(suites, dict) or set(suites) != set(SUITES):
        raise ValueError(f"release manifest must select exactly these suites: {', '.join(SUITES)}")
    for suite, spec in suites.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("run"), str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]*", spec["run"]):
            raise ValueError(f"release suite {suite}: run must be a name under runs/")
        if not isinstance(spec.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]):
            raise ValueError(f"release suite {suite}: sha256 must pin the raw run inputs")
        judges = spec.get("judges")
        if not isinstance(judges, list) or any(not isinstance(j, str) or not j for j in judges):
            raise ValueError(f"release suite {suite}: judges must be an explicit list (empty for local scoring)")
    return manifest


def build(root: Path, manifest_path: Path, out: Path) -> Path:
    manifest = load_manifest(manifest_path)
    models, _ = load_models(root)
    prepared = []
    # Validate every selected input before creating output or replacing existing generated pages.
    for suite in SUITES:
        spec = manifest["suites"][suite]
        run_dir = root / "runs" / spec["run"]
        snapshot = results.directory(root, suite, run_dir)
        if not run_dir.exists() and (snapshot / results.METADATA).is_file():
            results.restore(root, suite, run_dir)
        if not run_dir.is_dir():
            raise FileNotFoundError(f"release run not found: {run_dir}; restore its raw results bundle first")
        unknown = set(spec["judges"]) - models.keys()
        if unknown:
            raise ValueError(f"release suite {suite}: unknown judges {', '.join(sorted(unknown))}")
        validate_run_suite(run_dir, suite)
        bench = load_bench(root, suite)
        digest = bundle.input_digest(run_dir, bench)
        if digest != spec["sha256"]:
            raise ValueError(f"release suite {suite}: raw inputs changed (expected {spec['sha256']}, got {digest}); "
                             "review the changed run before updating the manifest")
        judges = set(spec["judges"])
        scores = scoring.aggregate(run_dir, bench.trait_weights, judges, bench=bench)
        stale = scores["stale_judgments"]
        if stale["total"]:
            raise ValueError(f"release suite {suite}: {stale['total']} stale judgments: {stale['reasons']}")
        prepared.append((suite, bench, run_dir, scores, judges))

    for suite, bench, run_dir, scores, judges in prepared:
        archive = bundle.export(run_dir, bench, out / "bundles", judges=judges, scores=scores)
        page_dir = out if suite == "core" else out / suite
        download = ("" if suite == "core" else "../") + f"bundles/{archive.name}"
        site.build(bench, models, run_dir, scores, page_dir, repo_url=manifest.get("repo_url"),
                   suite_tabs=True, bundle_url=download)
        write_json(page_dir / "scores.json", scores)
    write_json(out / "release.json", {
        "manifest": manifest,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "build_revision": site._revision(root),
    })
    (out / ".nojekyll").touch()
    return out / "index.html"
