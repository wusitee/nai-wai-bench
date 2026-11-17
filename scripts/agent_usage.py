#!/usr/bin/env python3
"""Snapshot the coding-agent tokens spent building this repository into results/agent-usage.json.

Reads `toktop-collector --snapshot` (https://github.com/wusitee/toktop) and writes aggregate totals per
agent model for the sessions whose project directory is in scope: at or below this checkout, one of its
current Git worktrees or an `--include` directory, or below any directory named like the main checkout
(which also catches worktrees that have since been removed). Directories with an `nwb-` component are the
benchmark's own working directories; those calls are counted from results/ and are left out here. The
site's token bill reads the file; rerun this before publishing to refresh it.
"""

import argparse
import datetime
import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUCKETS = {"input": ("input",), "cache_read": ("cache_read",), "cache_write": ("cache_write",),
           "output": ("output", "reasoning")}  # toktop reports reasoning apart from output
BENCH_PREFIX = "nwb-"  # backends run each benchmark call in a temporary directory with this prefix


def worktrees() -> list[Path]:
    """The main checkout first, then its other current Git worktrees; this checkout alone without Git."""
    done = subprocess.run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True, text=True)
    listed = [Path(line.split(" ", 1)[1]) for line in done.stdout.splitlines() if line.startswith("worktree ")]
    return listed if done.returncode == 0 and listed else [ROOT]


def in_scope(project: str, name: str, roots: list[Path]) -> bool:
    path = Path(project)
    if not project or any(part.startswith(BENCH_PREFIX) for part in path.parts):
        return False
    return name in path.parts or any(path == root or root in path.parents for root in roots)


def merge(seen: dict, event: dict) -> None:
    """Fold another copy of one response into the first, as toktop's own totals do: the largest count of
    each field, except that an input count already split from its cache reads wins over an unsplit one."""
    split = bool(event.get("input_is_split"))
    for field, count in event["tokens"].items():
        if field == "input" and split != seen["split"]:
            if split:
                seen["tokens"]["input"] = count or 0
            continue
        seen["tokens"][field] = max(seen["tokens"].get(field) or 0, count or 0)
    seen["split"] |= split


def collect(snapshot: dict, name: str, roots: list[Path]) -> list[dict]:
    """In-scope events. A response copied into several log files (resumed or forked sessions) carries one
    key and is counted once, at its first copy."""
    keyed, events = {}, []
    for tool, session in snapshot["sessions"]:
        if not in_scope(session.get("project") or "", name, roots):
            continue
        for event in session["events"]:
            key = (tool, event["key"]) if event.get("key") else None
            if key in keyed:
                merge(keyed[key], event)
                continue
            row = {"session": (tool, session["id"]), "model": session["models"][event["model"]], "ts": event["ts"],
                   "tokens": dict(event["tokens"]), "split": bool(event.get("input_is_split"))}
            events.append(row)
            if key:
                keyed[key] = row
    return events


def main() -> None:
    roots = worktrees()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", default=roots[0].name,
                        help=f"directory name that marks a checkout or its worktree parent (default: {roots[0].name})")
    parser.add_argument("--include", action="append", default=[], metavar="DIR",
                        help="also count sessions at or below DIR, such as a separate clone; repeatable")
    parser.add_argument("--snapshot", help="read a saved toktop-collector snapshot instead of running the collector")
    parser.add_argument("--out", default=str(ROOT / "results" / "agent-usage.json"))
    args = parser.parse_args()

    raw = (Path(args.snapshot).read_bytes() if args.snapshot
           else subprocess.run(["toktop-collector", "--snapshot"], capture_output=True, check=True).stdout)
    roots = [ROOT, *roots, *(Path(d).expanduser().resolve() for d in args.include)]
    models: dict[str, dict] = defaultdict(lambda: {"requests": 0, "tokens": dict.fromkeys(BUCKETS, 0)})
    sessions, stamps = set(), []
    for event in collect(json.loads(raw), args.name, roots):
        counts = {bucket: sum(event["tokens"].get(f) or 0 for f in fields) for bucket, fields in BUCKETS.items()}
        if not any(counts.values()):
            continue
        row = models[event["model"]]
        row["requests"] += 1
        for bucket, count in counts.items():
            row["tokens"][bucket] += count
        sessions.add(event["session"])
        stamps.append(event["ts"])
    if not stamps:
        raise SystemExit(f"no agent sessions found for project directory {args.name!r}")

    day = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date().isoformat()
    rows = sorted(({"model": name, **row} for name, row in models.items()),
                  key=lambda r: (-sum(r["tokens"].values()), r["model"]))
    data = {"source": "toktop-collector snapshot of local coding-agent logs",
            "first_day": day(min(stamps)), "last_day": day(max(stamps)),
            "sessions": len(sessions), "requests": sum(r["requests"] for r in rows), "models": rows}
    Path(args.out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {sum(sum(r['tokens'].values()) for r in rows):,} tokens, {len(sessions)} sessions, "
          f"{data['first_day']} to {data['last_day']}")


if __name__ == "__main__":
    main()
