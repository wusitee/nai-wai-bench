import argparse
import os
import sys
from pathlib import Path

from nwb import __version__, bundle, judge, release, report, results, scoring, site, tracks
from nwb.config import SUITES, find_root, load_bench, load_models, select_models, validate_run_suite
from nwb.util import write_json


def _items(bench, spec: str | None):
    if not spec:
        return bench.items
    if spec in ("vision", "text"):
        return [i for i in bench.items if i.modality == spec]
    if spec == "states":
        return bench.state_items
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    # "write_prompt" selects every per-animal expansion such as write_prompt.cat.
    items = [i for i in bench.all_items if any(i.id == w or i.id.startswith(w + ".") for w in wanted)]
    if not items:
        raise ValueError(f"no items match {spec!r}; see `nwb list`")
    return items


def _tiers(bench, spec: str | None):
    if not spec:
        return list(bench.tiers.values())
    if spec == "states":
        return list(bench.state_tiers.values())
    names = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [n for n in names if n not in bench.all_tiers]
    if unknown:
        raise ValueError(f"unknown tier(s) {unknown}; choose from: {', '.join(bench.all_tiers)}")
    return [bench.all_tiers[n] for n in names]


def cmd_list(args, root, bench, models, defaults):
    print(f"Suite: {bench.suite}")
    print("Models (backend, vendor, can):")
    for m in models.values():
        print(f"  {m.name:20} {m.backend:7} {m.vendor:10} {','.join(sorted(m.can))}")
    print(f"Default judges: {', '.join(defaults.get('judges', []))}")
    print("Understanding items:")
    for i in bench.all_items:
        extra = " (optional states)" if i.state else ""
        print(f"  {i.id:24} {i.modality:7} {i.lang}{extra}")
    print(f"Image tiers: {', '.join(bench.tiers)}")
    print(f"Optional state tiers (--tiers states): {', '.join(bench.state_tiers)}")
    print(f"Default state-suite animals: {', '.join(bench.state_animals)}")
    print("Animals (* = default subset): " + ", ".join(
        f"{a.id}{'*' if a.default else ''}" for a in bench.animals.values()))
    return 0


def cmd_understand(args, root, bench, models, defaults):
    selected = select_models(models, args.models, "text")
    jobs = tracks.understanding_jobs(bench, selected, _items(bench, args.items), args.reps, args.run_dir)
    return _collect(args, root, bench, jobs)


def cmd_imagegen(args, root, bench, models, defaults):
    selected = select_models(models, args.models, "image")
    tiers = _tiers(bench, args.tiers)
    animals = bench.select_animals(args.animals)
    if tiers and all(t.state for t in tiers) and args.animals == "default":
        animals = [bench.animals[a] for a in bench.state_animals]
    jobs = tracks.imagegen_jobs(bench, selected, tiers, animals, args.reps, args.run_dir)
    return _collect(args, root, bench, jobs)


def cmd_judge(args, root, bench, models, defaults):
    track_names = ["understanding", "imagegen"] if args.track == "all" else [args.track]
    jobs = []
    for track in track_names:
        default = defaults.get("image_judges" if track == "imagegen" else "judges") or defaults.get("judges", [])
        names = args.judges or ",".join(default)
        judges = [models[n] for n in select_names(models, names)]
        jobs += judge.judge_jobs(bench, judges, args.run_dir, {track})
    if not jobs:
        print("no judge calls needed; grounding checks are scored locally by `nwb report`", file=sys.stderr)
    return _collect(args, root, bench, jobs)


def _collect(args, root, bench, jobs):
    outcome = tracks.run_jobs(jobs, args.jobs, args.force, run_dir=args.run_dir)
    _sync_results(args, root, bench)
    return _finish(*outcome)


def _sync_results(args, root, bench, *, judges=None, scores=None):
    if getattr(args, "no_sync", False):
        return
    has_samples = any(next((args.run_dir / track).glob(pattern), None) is not None
                      for track, pattern in (("understanding", "*/*.json"), ("imagegen", "*/*/*.json")))
    if not has_samples:
        return
    snapshot = results.sync(root, bench, args.run_dir, judges=judges, scores=scores)
    print(f"saved results to {snapshot}")


def cmd_report(args, root, bench, models, defaults):
    if not args.run_dir.is_dir():
        raise FileNotFoundError(f"run not found: {args.run_dir}")
    judges = set(select_names(models, args.judges)) if args.judges is not None else None
    scores = scoring.aggregate(args.run_dir, bench.trait_weights, judges, bench=bench)
    write_json(args.run_dir / "scores.json", scores)
    html_path = args.run_dir / "report.html"
    html_path.write_text(report.render(bench, args.run, scores), encoding="utf-8")
    _sync_results(args, root, bench, judges=judges, scores=scores)
    for track, rows in scores["leaderboards"].items():
        print(track)
        for row in rows:
            rank = row["rank"] if row["rank"] is not None else "–"
            print(f"  {rank!s:>2}  {row['label']:25} {report.score_text(row)}  "
                  f"rank range {report.rank_range(row)}  {row['completed']}/{row['required']} cells  "
                  f"{report.row_details(row) or row['status']}")
    print(f"wrote {html_path}")
    return 0


def cmd_site(args, root, bench, models, defaults):
    if not args.run_dir.is_dir():
        raise FileNotFoundError(f"run not found: {args.run_dir}")
    judges = set(select_names(models, args.judges)) if args.judges is not None else None
    scores = scoring.aggregate(args.run_dir, bench.trait_weights, judges, bench=bench)
    out = Path(args.out) if args.out else root / "site"
    index = site.build(bench, models, args.run_dir, scores, out, repo_url=args.repo_url,
                       suite_tabs=args.suite_tabs, bundle_url=args.bundle_url)
    print(f"wrote {index}")
    return 0


def cmd_export(args, root, bench, models, defaults):
    archive = bundle.export(args.run_dir, bench, Path(args.out) if args.out else args.run_dir)
    print(f"wrote {archive}")
    return 0


def cmd_sync(args, root, bench, models, defaults):
    judges = set(select_names(models, args.judges)) if args.judges is not None else None
    snapshot = results.sync(root, bench, args.run_dir, judges=judges)
    print(f"saved results to {snapshot}")
    return 0


def cmd_restore(args, root, bench, models, defaults):
    path = results.restore(root, bench.suite, args.run_dir)
    print(f"restored {path}")
    return 0


def select_names(models, spec: str) -> list[str]:
    names = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [n for n in names if n not in models]
    if unknown:
        raise ValueError(f"unknown model(s) {unknown}; choose from: {', '.join(models)}")
    return names


def _finish(ok: int, failed: int) -> int:
    print(f"done: {ok} ok, {failed} failed", file=sys.stderr)
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="nwb", description="大笑奶龙 / 奶蛙 understanding and image-generation benchmark")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    def with_run(sp, jobs=True, sync=False):
        sp.add_argument("--suite", choices=SUITES, default="core", help="evaluation suite (default: core)")
        sp.add_argument("--run", default="main", help="run name; results go to runs/<run>/ (default: main)")
        if jobs:
            sp.add_argument("--jobs", type=int, default=2, help="parallel calls (default: 2)")
            sp.add_argument("--force", action="store_true", help="redo samples that already succeeded")
        if sync:
            sp.add_argument("--no-sync", action="store_true", help="skip saving a Git-ready results snapshot")
        return sp

    sp = sub.add_parser("list", help="show models, items, tiers, and animals")
    sp.add_argument("--suite", choices=SUITES, default="core", help="evaluation suite (default: core)")

    sp = with_run(sub.add_parser("understand", help="part 1: ask models about the meme"), sync=True)
    sp.add_argument("--models", required=True, help="comma-separated model names")
    sp.add_argument("--items", help="'vision', 'text', 'states', or comma-separated ids/prefixes (default: suite's main items)")
    sp.add_argument("--reps", type=int, default=1, help="samples per item (default: 1)")

    sp = with_run(sub.add_parser("imagegen", help="part 2: generate meme-style animal images"), sync=True)
    sp.add_argument("--models", required=True, help="comma-separated image model names")
    sp.add_argument("--tiers", help="'states' or comma-separated tiers (default: five core tiers)")
    sp.add_argument("--animals", default="default", help="'default', 'all', or ids (states default: cat,frog)")
    sp.add_argument("--reps", type=int, default=1, help="images per prompt (default: 1)")

    sp = with_run(sub.add_parser("judge", help="score results with judge models"), sync=True)
    sp.add_argument("--judges", help="comma-separated judge models (default: [defaults].judges, "
                    "and [defaults].image_judges for imagegen)")
    sp.add_argument("--track", choices=["understanding", "imagegen", "all"], default="all")

    sp = with_run(sub.add_parser("report", help="aggregate scores and write report.html"), jobs=False, sync=True)
    sp.add_argument("--judges", help="comma-separated judges to count (default: every judge with results)")

    sp = with_run(sub.add_parser("site", help="build a static results site (for GitHub Pages)"), jobs=False)
    sp.add_argument("--out", help="output directory (default: site/)")
    sp.add_argument("--judges", help="comma-separated judges to count (default: every judge with results)")
    sp.add_argument("--bundle-url", help="download URL for the raw results zip")
    sp.add_argument("--repo-url", help="link to the source repository in the footer")
    sp.add_argument("--suite-tabs", action="store_true",
                    help="link every suite's page, assuming core at the site root and others in <suite>/")
    sp = with_run(sub.add_parser("export", help="export a portable raw results bundle"), jobs=False)
    sp.add_argument("--out", help="output directory (default: run directory)")
    sp = with_run(sub.add_parser("sync", help="save an existing run as Git-ready results"), jobs=False)
    sp.add_argument("--judges", help="comma-separated recorded judges to count (default: all)")
    with_run(sub.add_parser("restore", help="restore working files from saved repository results"), jobs=False)
    sp = sub.add_parser("release", help="build both suites and raw bundles from a pinned release manifest (offline)")
    sp.add_argument("--manifest", required=True, help="release TOML selecting runs, content hashes, and judges")
    sp.add_argument("--out", help="output directory (default: site/)")
    return p


COMMANDS = {"list": cmd_list, "understand": cmd_understand, "imagegen": cmd_imagegen,
            "judge": cmd_judge, "report": cmd_report, "site": cmd_site, "export": cmd_export,
            "sync": cmd_sync, "restore": cmd_restore}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = find_root()
        os.environ.setdefault("NWB_ROOT", str(root))
        if args.command == "release":
            index = release.build(root, Path(args.manifest), Path(args.out) if args.out else root / "site")
            print(f"wrote {index}")
            return 0
        bench = load_bench(root, args.suite)
        models, defaults = load_models(root)
        if hasattr(args, "run"):
            args.run_dir = root / "runs" / args.run
            if (not args.run_dir.exists() and args.command != "restore"
                    and args.run_dir.parent == root / "runs"
                    and (root / "results" / bench.suite / args.run / results.METADATA).is_file()):
                results.restore(root, bench.suite, args.run_dir)
            validate_run_suite(args.run_dir, bench.suite)
            if (hasattr(args, "no_sync") and not args.no_sync) or args.command == "sync":
                results.directory(root, bench.suite, args.run_dir)
        return COMMANDS[args.command](args, root, bench, models, defaults)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
