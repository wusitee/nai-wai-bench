#!/usr/bin/env python3
"""Snapshot the coding-agent tokens spent building this repository into results/agent-usage.json.

Reads `toktop-collector --snapshot` (https://github.com/wusitee/toktop), keeps sessions whose project
directory is this checkout, a sibling clone named after it, or a worktree below a directory with its
name, and writes aggregate totals per agent model. Benchmark calls run in their own temporary
directories and are counted from results/ instead, so they are not included here. The site's token
bill reads the file; rerun this before publishing to refresh it.
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--name", default=ROOT.name, help=f"project directory name to match (default: {ROOT.name})")
    parser.add_argument("--snapshot", help="read a saved toktop-collector snapshot instead of running the collector")
    parser.add_argument("--out", default=str(ROOT / "results" / "agent-usage.json"))
    args = parser.parse_args()

    raw = (Path(args.snapshot).read_bytes() if args.snapshot
           else subprocess.run(["toktop-collector", "--snapshot"], capture_output=True, check=True).stdout)
    models: dict[str, dict] = defaultdict(lambda: {"requests": 0, "tokens": dict.fromkeys(BUCKETS, 0)})
    sessions, stamps = 0, []
    for _tool, session in json.loads(raw)["sessions"]:
        parts = Path(session.get("project") or "").parts
        if not any(part == args.name or part.startswith(args.name + "-") for part in parts):
            continue
        sessions += bool(session["events"])
        for event in session["events"]:
            row = models[session["models"][event["model"]]]
            row["requests"] += 1
            for bucket, fields in BUCKETS.items():
                row["tokens"][bucket] += sum(event["tokens"].get(f) or 0 for f in fields)
            stamps.append(event["ts"])
    if not stamps:
        raise SystemExit(f"no agent sessions found for project directory {args.name!r}")

    day = lambda ms: datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).date().isoformat()
    rows = sorted(({"model": name, **row} for name, row in models.items()),
                  key=lambda r: (-sum(r["tokens"].values()), r["model"]))
    data = {"source": "toktop-collector snapshot of local coding-agent logs",
            "first_day": day(min(stamps)), "last_day": day(max(stamps)),
            "sessions": sessions, "requests": sum(r["requests"] for r in rows), "models": rows}
    Path(args.out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {sum(sum(r['tokens'].values()) for r in rows):,} tokens, {sessions} sessions, "
          f"{data['first_day']} to {data['last_day']}")


if __name__ == "__main__":
    main()
