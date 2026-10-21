import argparse
import os
import sys
from pathlib import Path

from nwb import judge, report, scoring, tracks
from nwb.config import find_root, load_bench, load_models, select_models
from nwb.util import write_json


def _items(bench, spec: str | None):
    if not spec:
        return bench.items
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    # "write_prompt" selects every per-animal expansion such as write_prompt.cat.
    items = [i for i in bench.items if any(i.id == w or i.id.startswith(w + ".") for w in wanted)]
    if not items:
        raise ValueError(f"no items match {spec!r}; see `nwb list`")
    return items


def _tiers(bench, spec: str | None):
    if not spec:
        return list(bench.tiers.values())
    names = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [n for n in names if n not in bench.tiers]
    if unknown:
        raise ValueError(f"unknown tier(s) {unknown}; choose from: {', '.join(bench.tiers)}")
    return [bench.tiers[n] for n in names]


def cmd_list(args, root, bench, models, defaults):
    print("Models (backend, vendor, can):")
    for m in models.values():
        print(f"  {m.name:20} {m.backend:7} {m.vendor:10} {','.join(sorted(m.can))}")
    print(f"Default judges: {', '.join(defaults.get('judges', []))}")
    print("Understanding items:")
    for i in bench.items:
        print(f"  {i.id:24} {i.modality:7} {i.lang}")
    print(f"Image tiers: {', '.join(bench.tiers)}")
    print("Animals (* = default subset): " + ", ".join(
        f"{a.id}{'*' if a.default else ''}" for a in bench.animals.values()))
    return 0


def cmd_understand(args, root, bench, models, defaults):
    selected = select_models(models, args.models, "text")
    jobs = tracks.understanding_jobs(bench, selected, _items(bench, args.items), args.reps, args.run_dir)
    return _finish(*tracks.run_jobs(jobs, args.jobs, args.force))


def cmd_imagegen(args, root, bench, models, defaults):
    selected = select_models(models, args.models, "image")
    jobs = tracks.imagegen_jobs(bench, selected, _tiers(bench, args.tiers), bench.select_animals(args.animals),
                                args.reps, args.run_dir)
    return _finish(*tracks.run_jobs(jobs, args.jobs, args.force))


def cmd_judge(args, root, bench, models, defaults):
    track_names = ["understanding", "imagegen"] if args.track == "all" else [args.track]
    jobs = []
    for track in track_names:
        default = defaults.get("image_judges" if track == "imagegen" else "judges") or defaults.get("judges", [])
        names = args.judges or ",".join(default)
        judges = [models[n] for n in select_names(models, names)]
        jobs += judge.judge_jobs(bench, judges, args.run_dir, {track})
    if not jobs:
        print("nothing to judge; run `nwb understand` or `nwb imagegen` first", file=sys.stderr)
        return 1
    return _finish(*tracks.run_jobs(jobs, args.jobs, args.force))


def cmd_report(args, root, bench, models, defaults):
    scores = scoring.aggregate(args.run_dir, bench.trait_weights)
    write_json(args.run_dir / "scores.json", scores)
    html_path = args.run_dir / "report.html"
    html_path.write_text(report.render(bench, args.run, scores), encoding="utf-8")
    for model, s in sorted(scores["understanding"].items(), key=lambda kv: -(kv[1]["overall"] or 0)):
        print(f"understanding  {model:20} overall {report.fmt(s['overall']):>3}  "
              f"text {report.fmt(s['text']):>3}  vision {report.fmt(s['vision']):>3}")
    for model, s in sorted(scores["imagegen"].items(), key=lambda kv: -(kv[1]["overall"] or 0)):
        tiers = "  ".join(f"{t} {report.fmt(v['overall'])}" for t, v in s["tiers"].items())
        print(f"imagegen       {model:20} overall {report.fmt(s['overall']):>3}  {tiers}")
    print(f"wrote {html_path}")
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
    sub = p.add_subparsers(dest="command", required=True)

    def with_run(sp, jobs=True):
        sp.add_argument("--run", default="main", help="run name; results go to runs/<run>/ (default: main)")
        if jobs:
            sp.add_argument("--jobs", type=int, default=2, help="parallel calls (default: 2)")
            sp.add_argument("--force", action="store_true", help="redo samples that already succeeded")
        return sp

    sub.add_parser("list", help="show models, items, tiers, and animals")

    sp = with_run(sub.add_parser("understand", help="part 1: ask models about the meme"))
    sp.add_argument("--models", required=True, help="comma-separated model names")
    sp.add_argument("--items", help="comma-separated item ids (default: all)")
    sp.add_argument("--reps", type=int, default=1, help="samples per item (default: 1)")

    sp = with_run(sub.add_parser("imagegen", help="part 2: generate meme-style animal images"))
    sp.add_argument("--models", required=True, help="comma-separated image model names")
    sp.add_argument("--tiers", help="comma-separated tiers (default: all)")
    sp.add_argument("--animals", default="default", help="'default', 'all', or comma-separated ids")
    sp.add_argument("--reps", type=int, default=1, help="images per prompt (default: 1)")

    sp = with_run(sub.add_parser("judge", help="score results with judge models"))
    sp.add_argument("--judges", help="comma-separated judge models (default: [defaults].judges, "
                    "and [defaults].image_judges for imagegen)")
    sp.add_argument("--track", choices=["understanding", "imagegen", "all"], default="all")

    with_run(sub.add_parser("report", help="aggregate scores and write report.html"), jobs=False)
    return p


COMMANDS = {"list": cmd_list, "understand": cmd_understand, "imagegen": cmd_imagegen,
            "judge": cmd_judge, "report": cmd_report}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = find_root()
        os.environ.setdefault("NWB_ROOT", str(root))
        bench = load_bench(root)
        models, defaults = load_models(root)
        if hasattr(args, "run"):
            args.run_dir = root / "runs" / args.run
        return COMMANDS[args.command](args, root, bench, models, defaults)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
