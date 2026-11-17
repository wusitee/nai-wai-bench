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
from nwb.provenance import collection_profile
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
    """Mean output tokens per task for each effort of a model, on the tasks all its efforts answered.

    Calls are pooled by effort and collection profile, whichever registry entry made them. Efforts
    collected under different profiles stay separate steps and mark the ladder as mixed: its gaps are
    then not the effect of effort alone.
    """
    out = []
    for (model, _backend, role), steps in tasks.items():
        if len({effort for effort, _ in steps}) < 2:
            continue
        shared = set.intersection(*(set(by_task) for by_task in steps.values()))
        if not shared:
            continue
        rows = [{"effort": effort, "profile": profile, "mean_output": fmean(fmean(by_task[task]) for task in shared)}
                for (effort, profile), by_task in steps.items()]
        rows.sort(key=lambda s: (effort_rank(s["effort"]), s["profile"]))
        out.append({"model": model, "role": role, "tasks": len(shared),
                    "mixed_profiles": len({profile for _, profile in steps}) > 1, "steps": rows})
    return sorted(out, key=lambda ladder: (ladder["role"] != "understanding", ladder["model"]))


def summary(root: Path, models: dict[str, ModelSpec], calls: list[dict]) -> dict:
    """Totals by track, by registry entry with its recorded model and effort, and effort comparisons."""
    tokens = dict.fromkeys(BUCKETS, 0)
    tracks: dict[tuple, dict] = {}
    entries: dict[tuple, dict] = {}
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
        # An entry whose settings changed between runs gets one row per recorded configuration.
        entry = entries.setdefault((call["entry"], model, effort), {
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
        if role in TASKS and effort in EFFORTS:  # an unranked effort has no place on a ladder
            task = (suite, *(record.get(k) for k in TASKS[role]))
            backend = settings.get("backend") or (spec.backend if spec else "")
            tasks[model, backend, role][effort, collection_profile(record)][task].append(used["output"])

    agents = load_agent_usage(root)
    total = sum(tokens.values()) + (sum(agents["tokens"].values()) if agents else 0)
    return {"total": total, "calls": len(calls),
            "no_usage_calls": sum(t["no_usage_calls"] for t in tracks.values()),
            "tokens": tokens, "agents": agents,
            "tracks": sorted(tracks.values(), key=lambda t: -t["tokens"]),
            "entries": sorted(entries.values(), key=lambda r: (r["model"], effort_rank(r["effort"]), r["entry"])),
            "ladders": _ladders(tasks)}
