import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nwb import bill
from nwb.config import ModelSpec
from nwb.contributions import UNCOMMITTED, credited_calls, leaderboard

PRICE = {"input": 2.0, "cached_input": 0.5, "cache_write": 3.0, "output": 10.0}


def _record(path, model, tokens, started, resolved=None, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "track": "understanding", **extra,
                                "collected": {"started_at": started},
                                "meta": {"seconds": 1.0, "tokens": tokens, "resolved_model": resolved}}),
                    encoding="utf-8")


def _spec(name, model, price):
    return ModelSpec(name=name, backend="claude", vendor="v", model=model, can=frozenset({"text"}),
                     options={"price": price})


def _git(root, *args, author="Setup", when=1_700_000_000):
    env = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_DATE": f"{when} +0000",
           "GIT_AUTHOR_EMAIL": "a@example.invalid",
           "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "a@example.invalid"}
    subprocess.run(["git", *args], cwd=root, check=True, env=env)


def _commit(root, author, when, *flags):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", author, *flags, author=author, when=when)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_calls_are_priced_deduplicated_and_credited(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)  # no dependence on the machine's signing or identity
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _git(tmp_path, "init", "-q")
    priced = {"input": 1_000_000, "cached_input": 200_000, "cache_write": 100_000, "output": 100_000}
    zoe = tmp_path / "results/core/zoe"
    (zoe / "snapshot.json").parent.mkdir(parents=True)
    (zoe / "snapshot.json").write_text("{}")
    _record(zoe / "understanding/paid/a__r1.json", "paid", priced, "t1")
    _record(zoe / "understanding/free/a__r1.json", "unlisted", priced, "t2")
    _record(zoe / "understanding/paid/b__r1.json", "paid", {"input": None, "output": None}, "t3")
    _commit(tmp_path, "Zoe", 1_700_000_000)

    # A merged run repeats Zoe's call with rewritten bytes; Bob judges it, and one call stays uncommitted.
    # Bob's records first appear in a Git merge commit, which must be credited like any other commit.
    _git(tmp_path, "checkout", "-qb", "side")
    _commit(tmp_path, "Side", 1_700_000_050, "--allow-empty")
    _git(tmp_path, "checkout", "-q", "-")
    _git(tmp_path, "merge", "-q", "--no-ff", "--no-commit", "side")
    merged = tmp_path / "results/core/merged"
    shutil.copytree(zoe, merged)
    _record(merged / "understanding/paid/a__r1.json", "paid", priced, "t1", note="re-synced")
    _record(merged / "judgments/paid/understanding/paid/a__r1.json", "paid",
            {"input": 1_000_000, "output": 0}, "t4", judge="paid")
    _commit(tmp_path, "Bob", 1_700_000_100)
    _record(merged / "understanding/paid/c__r1.json", "paid", {"input": 10, "output": 0}, "t5")

    models = {"paid": _spec("paid", "m-1", PRICE)}
    board = leaderboard(tmp_path, models, credits={"runs": {}, "aliases": {"Bob": "Robert"}})
    rows = {r["contributor"]: r for r in board["contributors"]}
    assert board["calls"] == 5
    zoe_row = rows["Zoe"]
    # 0.7M plain input * $2 + 0.2M cached * $0.5 + 0.1M write * $3 + 0.1M output * $10
    assert zoe_row["usd"] == pytest.approx(1.4 + 0.1 + 0.3 + 1.0)
    unlisted = next(m for m in zoe_row["models"] if m["model"] == "unlisted")
    assert unlisted["usd"] is None and unlisted["unpriced_calls"] == 1
    assert zoe_row["no_usage_calls"] == 1 and zoe_row["rank"] == 1
    assert rows["Robert"]["usd"] == pytest.approx(2.0) and rows["Robert"]["models"][0]["roles"] == ["judge"]
    assert rows[UNCOMMITTED]["calls"] == 1

    # A run credit overrides Git authorship for collected calls, not for judgments.
    board = leaderboard(tmp_path, models, credits={"runs": {"core/zoe": "Carol"}, "aliases": {}})
    rows = {r["contributor"]: r for r in board["contributors"]}
    assert "Zoe" not in rows and rows["Carol"]["calls"] == 3 and rows["Bob"]["calls"] == 1


def test_retired_entries_use_agreeing_rates_but_image_relays_stay_unpriced(tmp_path):
    run = tmp_path / "results/core/run"
    (run / "snapshot.json").parent.mkdir(parents=True)
    (run / "snapshot.json").write_text("{}")
    tokens = {"input": 1_000_000, "output": 0}
    _record(run / "understanding/retired/a__r1.json", "retired", tokens, "t1", resolved="m-1")
    _record(run / "understanding/split/a__r1.json", "split", tokens, "t2", resolved="m-2")
    _record(run / "imagegen/relay/a__r1.json", "relay", tokens, "t3", resolved="m-1", track="imagegen")

    # m-1 entries share rates and differ only in price metadata; m-2 entries disagree on a rate.
    models = {"a": _spec("a", "m-1", {**PRICE, "as_of": "2026-01-01"}),
              "b": _spec("b", "m-1", {**PRICE, "as_of": "2026-02-02"}),
              "c": _spec("c", "m-2", PRICE), "d": _spec("d", "m-2", {**PRICE, "input": 4.0})}
    board = leaderboard(tmp_path, models, authors={}, credits={"runs": {}, "aliases": {}})
    usd = {m["model"]: m["usd"] for m in board["contributors"][0]["models"]}
    assert usd == {"retired": pytest.approx(2.0), "split": None, "relay": None}


def test_bill_sums_disjoint_buckets_and_compares_efforts_on_shared_tasks(tmp_path):
    run = tmp_path / "results/core/run"
    (run / "snapshot.json").parent.mkdir(parents=True)
    (run / "snapshot.json").write_text("{}")
    high, top = {"model": "m-1", "effort": "high"}, {"model": "m-1", "effort": "max"}
    usage = lambda output: {"input": 100, "cached_input": 60, "cache_write": 10, "output": output}
    answer = lambda entry, item, output, settings, rep=1: _record(
        run / f"understanding/{entry}/{item}__r{rep}.json", entry, usage(output), f"{entry}{item}{rep}", item=item,
        settings=settings)
    # High is split over two entries (a, b and d); max answered a twice and d. Only a and d are shared.
    answer("hi", "a", 10, high), answer("hi", "b", 1000, high), answer("hi2", "d", 30, high)
    answer("top", "a", 40, top), answer("top", "a", 60, top, rep=2), answer("top", "d", 90, top)
    _record(run / "understanding/top/c__r1.json", "top", {"input": None, "output": None}, "t5", item="c", settings=top)
    answer("hi", "e", 7, top)  # the entry's settings changed between runs
    answer("odd", "a", 5, {"model": "m-1", "effort": "default"})  # unranked effort: no ladder step
    # Efforts collected under different Codex profiles are still compared, but flagged.
    answer("c-hi", "a", 3, {"model": "m-2", "effort": "high", "backend": "codex"})
    answer("c-top", "a", 4, {"model": "m-2", "effort": "max", "backend": "codex", "command": ["codex", "--disable", "x"]})
    (tmp_path / "results" / bill.AGENT_USAGE).write_text(json.dumps({"sessions": 2, "models": [
        {"model": "agent", "tokens": {"input": 1, "cache_read": 2, "cache_write": 3, "output": 4}}]}))

    calls = credited_calls(tmp_path, {}, authors={}, credits={"runs": {}, "aliases": {}})
    summary = bill.summary(tmp_path, {}, calls)
    assert summary["tokens"] == {"input": 300, "cache_read": 600, "cache_write": 100, "output": 1249}
    assert summary["total"] == 2249 + 10 and summary["no_usage_calls"] == 1
    assert [(r["entry"], r["effort"], r["calls"]) for r in summary["entries"]] == [
        ("odd", "default", 1), ("hi", "high", 2), ("hi2", "high", 1), ("hi", "max", 1), ("top", "max", 4),
        ("c-hi", "high", 1), ("c-top", "max", 1)]
    pooled, mixed = summary["ladders"]
    assert pooled["tasks"] == 2 and not pooled["mixed_profiles"]
    assert [(s["effort"], s["mean_output"]) for s in pooled["steps"]] == [("high", 20), ("max", 70)]
    assert mixed["mixed_profiles"] and [s["profile"] for s in mixed["steps"]] == ["", "Codex custom"]


def test_agent_usage_counts_a_copied_response_once_and_only_project_sessions(tmp_path):
    event = lambda key, **tokens: {"ts": 1_700_000_000_000, "model": 0, "key": key, "tokens": tokens}
    session = lambda sid, project, *events: ["Codex", {"id": sid, "project": project, "models": ["m"],
                                                       "events": list(events)}]
    (tmp_path / "snap.json").write_text(json.dumps({"version": 1, "sessions": [
        session("s1", "/w/proj", event("k1", input=10, output=5, reasoning=2)),
        # A resumed copy of k1 with more complete counts, in a since-removed worktree below the project name.
        session("s2", "/w/trees/proj/fork", event("k1", input=10, output=9, reasoning=2), event("k2", cache_read=100)),
        session("s3", "/w/proj-website", event("k3", input=1000)),  # another project
        session("s4", "/w/proj/.scratch/tmp/nwb-codex-abc", event("k4", input=1000)),  # a benchmark call
    ]}))
    script = Path(__file__).resolve().parent.parent / "scripts/agent_usage.py"
    subprocess.run([sys.executable, str(script), "--name", "proj", "--snapshot", str(tmp_path / "snap.json"),
                    "--out", str(tmp_path / "out.json")], check=True, capture_output=True)
    data = json.loads((tmp_path / "out.json").read_text())
    assert (data["sessions"], data["requests"]) == (2, 2)
    assert data["models"][0]["tokens"] == {"input": 10, "cache_read": 100, "cache_write": 0, "output": 11}
