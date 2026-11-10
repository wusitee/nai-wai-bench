"""Token-value contribution ranking: saved calls priced at API list prices, credited to contributors.

Every saved call record (subject answers, generated images, judgments, frontend pages) under `results/`
carries its token usage in `meta.tokens`. Each call is priced with its model entry's `price` table and
credited to whoever contributed it, so the ranking shows what the shared results would have cost at
pay-as-you-go API prices. Subscription CLIs are not billed per token; this is a value estimate, not a bill.
"""

import hashlib
import json
import subprocess
import tomllib
from collections import defaultdict
from pathlib import Path

from nwb.config import ModelSpec
from nwb.scoring import token_cost

CREDITS = "contributors.toml"
UNCOMMITTED = "(uncommitted)"
TOKEN_FIELDS = ("input", "cached_input", "cache_write", "output")


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def git_authors(root: Path) -> dict[str, tuple[int, str]]:
    """Map each blob ever committed under results/ to its earliest (author time, author name).

    Content identity survives renames, merged runs, and re-syncs that leave a record unchanged, so a
    record is credited to the commit that first introduced it, including a merge commit that adds
    records of its own. Author names follow `.mailmap`. Without Git history the map is empty."""
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=off", "log", "--raw", "--no-abbrev", "--full-history",
                              "-m", "--format=%x01%at%x09%aN", "--", "results"],
                             cwd=root, capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.CalledProcessError):
        return {}
    earliest: dict[str, tuple[int, str]] = {}
    when, author = 0, ""
    for line in out.splitlines():
        if line.startswith("\x01"):
            stamp, _, author = line[1:].partition("\t")
            when = int(stamp)
        elif line.startswith(":"):
            fields = line.split("\t", 1)[0].split()
            if len(fields) >= 5 and not fields[4].startswith("D"):
                blob = fields[3]
                if blob not in earliest or (when, author) < earliest[blob]:
                    earliest[blob] = (when, author)
    return earliest


def load_credits(root: Path) -> dict:
    path = root / "results" / CREDITS
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    for table in ("runs", "aliases"):
        section = data.get(table, {})
        if not isinstance(section, dict) or not all(isinstance(v, str) and v.strip() for v in section.values()):
            raise ValueError(f"{path}: [{table}] must map names to non-empty strings")
    return {"runs": data.get("runs", {}), "aliases": data.get("aliases", {})}


def _calls(root: Path):
    """Yield (call key, run key, is judgment, record, blob sha) for every saved call with a meta block."""
    base = root / "results"
    for snapshot in sorted(base.glob("*/*/snapshot.json")):
        run_dir = snapshot.parent
        run_key = run_dir.relative_to(base).as_posix()
        for path in sorted(run_dir.rglob("*.json")):
            if path.parent == run_dir:  # snapshot.json, scores.json, summary.json
                continue
            data = path.read_bytes()
            try:
                record = json.loads(data)
            except ValueError:
                continue
            if not isinstance(record, dict) or not isinstance(record.get("meta"), dict):
                continue
            judged = "judge" in record
            # The same call reappears in merged runs at the same relative path; judgment bytes may differ
            # there (rewritten target hashes), so identify a call by where and when it was made.
            name = path.relative_to(run_dir).as_posix()
            meta = record["meta"]
            key = json.dumps([name, record.get("collected"), meta.get("seconds"), meta.get("tokens")],
                             sort_keys=True, default=str)
            yield key, run_key, judged, record, _blob_sha(data)


def _rates(price: dict | None) -> tuple | None:
    """The billing rates `token_cost` applies, without price metadata such as source and check date."""
    if not price or "input" not in price or "output" not in price:
        return None
    return (price["input"], price.get("cached_input", price["input"]),
            price.get("cache_write", price["input"]), price["output"])


def _price(entry: str, record: dict, models: dict[str, ModelSpec]) -> dict | None:
    """The entry's price; an entry missing from the registry falls back to configured entries for the
    same resolved model id when their billing rates agree. Generated-image calls never fall back: their
    tokens describe the relay around the image tool, not image generation."""
    if entry in models:
        price = models[entry].options.get("price")
        return price if _rates(price) else None
    meta = record.get("meta", {})
    model_id = meta.get("resolved_model") or meta.get("model")
    if not model_id or ("judge" not in record and record.get("track") == "imagegen"):
        return None
    prices = {}
    for m in models.values():
        rates = _rates(m.options.get("price"))
        if m.model == model_id and rates:
            prices.setdefault(rates, m.options["price"])
    return next(iter(prices.values())) if len(prices) == 1 else None


def _usage(record: dict) -> dict | None:
    tokens = record.get("meta", {}).get("tokens") or {}
    if tokens.get("input") is None or tokens.get("output") is None:
        return None
    return {k: tokens.get(k) or 0 for k in TOKEN_FIELDS}


def leaderboard(root: Path, models: dict[str, ModelSpec], *, authors: dict | None = None,
                credits: dict | None = None) -> dict:
    authors = git_authors(root) if authors is None else authors
    credits = load_credits(root) if credits is None else credits
    calls: dict[str, dict] = {}
    for key, run_key, judged, record, blob in _calls(root):
        call = calls.setdefault(key, {"record": record, "judged": judged, "runs": [], "blobs": set()})
        call["runs"].append(run_key)
        call["blobs"].add(blob)

    people: dict[str, dict] = defaultdict(lambda: {"calls": 0, "runs": set(), "models": {}})
    for call in calls.values():
        record = call["record"]
        override = next((credits["runs"][r] for r in call["runs"] if r in credits["runs"]), None)
        introduced = min((authors[b] for b in call["blobs"] if b in authors), default=None)
        name = (override if override and not call["judged"]
                else introduced[1] if introduced else UNCOMMITTED)
        name = credits["aliases"].get(name, name)
        entry = record["judge"] if call["judged"] else record.get("model", "?")
        person = people[name]
        person["calls"] += 1
        person["runs"].update(call["runs"])
        row = person["models"].setdefault(entry, {
            "model": entry, "calls": 0, "priced_calls": 0, "unpriced_calls": 0, "no_usage_calls": 0,
            "tokens": dict.fromkeys(TOKEN_FIELDS, 0), "usd": 0.0, "price": None, "roles": set()})
        row["calls"] += 1
        row["roles"].add("judge" if call["judged"] else record.get("track", "subject"))
        usage, price = _usage(record), _price(entry, record, models)
        if usage is None:
            row["no_usage_calls"] += 1
            continue
        for k in TOKEN_FIELDS:
            row["tokens"][k] += usage[k]
        if price is None:
            row["unpriced_calls"] += 1
        else:
            row["priced_calls"] += 1
            row["usd"] += token_cost(usage, price)
            row["price"] = {k: price.get(k) for k in (*TOKEN_FIELDS, "source", "as_of") if k in price}

    rows = []
    for name, person in people.items():
        model_rows = sorted(person["models"].values(), key=lambda r: (-r["usd"], r["model"]))
        for r in model_rows:
            r["roles"] = sorted(r["roles"])
            if not r["priced_calls"]:
                r["usd"] = None  # no list price or no usage: unknown, never zero
        priced = [r["usd"] for r in model_rows if r["usd"] is not None]
        rows.append({"contributor": name, "usd": sum(priced) if priced else None, "calls": person["calls"],
                     "runs": sorted(person["runs"]), "models": model_rows,
                     "unpriced_calls": sum(r["unpriced_calls"] for r in model_rows),
                     "no_usage_calls": sum(r["no_usage_calls"] for r in model_rows)})
    rows.sort(key=lambda r: (r["usd"] is None, -(r["usd"] or 0), r["contributor"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank if row["usd"] is not None else None
    return {"unit": "USD at pay-as-you-go API list prices from models.toml `price`",
            "calls": len(calls), "contributors": rows}


def _tokens(n: int) -> str:
    return f"{n / 1e6:.2f}M" if n >= 1e5 else f"{n:,}"


def render_text(board: dict, *, details: bool = True) -> str:
    out = [f"Token value by contributor: {board['unit']}; {board['calls']} unique calls"]
    for row in board["contributors"]:
        rank = row["rank"] if row["rank"] is not None else "–"
        usd = f"${row['usd']:,.2f}" if row["usd"] is not None else "no priced usage"
        notes = [f"{row['calls']} calls", f"{len(row['runs'])} runs"]
        if row["unpriced_calls"]:
            notes.append(f"{row['unpriced_calls']} without list price")
        if row["no_usage_calls"]:
            notes.append(f"{row['no_usage_calls']} without usage")
        out.append(f"{rank!s:>3}  {row['contributor']:24} {usd:>14}  {', '.join(notes)}")
        if not details:
            continue
        for m in row["models"]:
            cost = (f"${m['usd']:,.2f}" if m["usd"] is not None
                    else "no list price" if m["unpriced_calls"] else "no usage")
            t = m["tokens"]
            usage = (f"in {_tokens(t['input'])} (cached {_tokens(t['cached_input'])}, "
                     f"write {_tokens(t['cache_write'])}) out {_tokens(t['output'])}"
                     if m["no_usage_calls"] < m["calls"] else "")
            extra = []
            if m["usd"] is not None and m["unpriced_calls"]:
                extra.append(f"{m['unpriced_calls']} unpriced")
            if m["no_usage_calls"] and usage:
                extra.append(f"{m['no_usage_calls']} without usage")
            out.append(f"       {m['model']:24} {cost:>17}  {m['calls']:>4} calls  "
                       + "  ".join(filter(None, [usage, f"[{', '.join(m['roles'])}]",
                                                 f"({', '.join(extra)})" if extra else ""])))
    return "\n".join(out)
