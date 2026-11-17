"""Token bill: what running the benchmark and building it consumed.

Running usage is summed from every unique saved call under `results/` (the calls `nwb contributions`
credits). Building usage is a committed snapshot of coding-agent logs, `results/agent-usage.json`, written
by `scripts/agent_usage.py`; it cannot be rebuilt from the repository. All token counts use disjoint
buckets: plain input, cache reads, cache writes, and output (which includes reasoning).
"""

import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean

from nwb.config import ModelSpec
from nwb.scoring import token_cost

AGENT_USAGE = "agent-usage.json"
BUCKETS = ("input", "cache_read", "cache_write", "output")
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
# Subject roles whose calls answer one comparable task each, with the fields that identify the task.
TASKS = {"understanding": ("item",), "frontend": ("task", "kind")}


def buckets(usage: dict) -> dict:
    """Disjoint buckets from a call's usage, whose `input` includes cache reads and writes."""
    return {"input": usage["input"] - usage["cached_input"] - usage["cache_write"],
            "cache_read": usage["cached_input"], "cache_write": usage["cache_write"], "output": usage["output"]}


def _add(total: dict, tokens: dict) -> None:
    for k in BUCKETS:
        total[k] += tokens[k]


def effort_rank(effort: str) -> int:
    return EFFORTS.index(effort) if effort in EFFORTS else -1


def load_agent_usage(root: Path) -> dict | None:
    path = root / "results" / AGENT_USAGE
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("models")
    if not isinstance(rows, list) or not all(
            isinstance(r, dict) and isinstance(r.get("model"), str) and isinstance(r.get("tokens"), dict)
            and all(isinstance(r["tokens"].get(k), int) for k in BUCKETS) for r in rows):
        raise ValueError(f"{path}: models must list a model name and integer {', '.join(BUCKETS)} tokens")
    tokens = dict.fromkeys(BUCKETS, 0)
    for row in rows:
        _add(tokens, row["tokens"])
    return {**data, "models": sorted(rows, key=lambda r: -sum(r["tokens"][k] for k in BUCKETS)), "tokens": tokens}


def _ladders(tasks: dict) -> list[dict]:
    """Mean output tokens per task for each effort of a model, on the tasks all its efforts answered."""
    out = []
    for (model, role), entries in tasks.items():
        if len({effort for _, effort in entries}) < 2:
            continue
        shared = set.intersection(*(set(by_task) for by_task in entries.values()))
        if not shared:
            continue
        steps = [{"entry": entry, "effort": effort,
                  "mean_output": fmean(fmean(by_task[task]) for task in shared)}
                 for (entry, effort), by_task in entries.items()]
        steps.sort(key=lambda s: (effort_rank(s["effort"]), s["entry"]))
        out.append({"model": model, "role": role, "tasks": len(shared), "steps": steps})
    return sorted(out, key=lambda ladder: (ladder["role"] != "understanding", ladder["model"]))


def summary(root: Path, models: dict[str, ModelSpec], calls: list[dict]) -> dict:
    """Totals by track, by registry entry with its reasoning effort, and effort comparisons."""
    tokens = dict.fromkeys(BUCKETS, 0)
    tracks: dict[tuple, dict] = {}
    entries: dict[str, dict] = {}
    tasks: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for call in calls:
        record, role, usage = call["record"], call["role"], call["usage"]
        suite = call["runs"][0].split("/", 1)[0]
        settings = record.get("settings") if isinstance(record.get("settings"), dict) else {}
        spec = models.get(call["entry"])
        model = settings.get("model") or (spec.model if spec else call["entry"])
        effort = settings.get("effort") or (spec.options.get("effort", "default") if spec else "default")
        track = tracks.setdefault((suite, role), {"suite": suite, "role": role, "calls": 0, "no_usage_calls": 0,
                                                  "tokens": 0})
        entry = entries.setdefault(call["entry"], {
            "entry": call["entry"], "model": model, "effort": effort, "calls": 0, "no_usage_calls": 0,
            "tokens": dict.fromkeys(BUCKETS, 0), "usd": None, "roles": {}})
        role_row = entry["roles"].setdefault(role, {"calls": 0, "usage_calls": 0, "output": 0})
        for row in (track, entry, role_row):
            row["calls"] += 1
        if usage is None:
            track["no_usage_calls"] += 1
            entry["no_usage_calls"] += 1
            continue
        used = buckets(usage)
        _add(tokens, used)
        _add(entry["tokens"], used)
        track["tokens"] += sum(used.values())
        role_row["usage_calls"] += 1
        role_row["output"] += used["output"]
        if call["price"] is not None:
            entry["usd"] = (entry["usd"] or 0.0) + token_cost(usage, call["price"])
        if role in TASKS:
            task = (suite, *(record.get(k) for k in TASKS[role]))
            tasks[model, role][call["entry"], effort][task].append(used["output"])

    agents = load_agent_usage(root)
    total = sum(tokens.values()) + (sum(agents["tokens"].values()) if agents else 0)
    return {"total": total, "calls": len(calls),
            "no_usage_calls": sum(t["no_usage_calls"] for t in tracks.values()),
            "tokens": tokens, "agents": agents,
            "tracks": sorted(tracks.values(), key=lambda t: -t["tokens"]),
            "entries": sorted(entries.values(), key=lambda r: (r["model"], effort_rank(r["effort"]), r["entry"])),
            "ladders": _ladders(tasks)}
