import json
import os
import shutil
import subprocess

import pytest

from nwb.config import ModelSpec
from nwb.contributions import UNCOMMITTED, leaderboard

PRICE = {"input": 2.0, "cached_input": 0.5, "cache_write": 3.0, "output": 10.0}


def _record(path, model, tokens, started, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"model": model, "track": "understanding", **extra,
                                "collected": {"started_at": started},
                                "meta": {"seconds": 1.0, "tokens": tokens}}), encoding="utf-8")


def _commit(root, author, when):
    env = {**os.environ, "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_DATE": f"{when} +0000",
           "GIT_AUTHOR_EMAIL": "a@example.invalid",
           "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": "a@example.invalid"}
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", author], cwd=root, check=True, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_calls_are_priced_deduplicated_and_credited(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    priced = {"input": 1_000_000, "cached_input": 200_000, "cache_write": 100_000, "output": 100_000}
    zoe = tmp_path / "results/core/zoe"
    (zoe / "snapshot.json").parent.mkdir(parents=True)
    (zoe / "snapshot.json").write_text("{}")
    _record(zoe / "understanding/paid/a__r1.json", "paid", priced, "t1")
    _record(zoe / "understanding/free/a__r1.json", "unlisted", priced, "t2")
    _record(zoe / "understanding/paid/b__r1.json", "paid", {"input": None, "output": None}, "t3")
    _commit(tmp_path, "Zoe", 1_700_000_000)

    # A merged run repeats Zoe's call with rewritten bytes; Bob judges it, and one call stays uncommitted.
    merged = tmp_path / "results/core/merged"
    shutil.copytree(zoe, merged)
    _record(merged / "understanding/paid/a__r1.json", "paid", priced, "t1", note="re-synced")
    _record(merged / "judgments/paid/understanding/paid/a__r1.json", "paid",
            {"input": 1_000_000, "output": 0}, "t4", judge="paid")
    _commit(tmp_path, "Bob", 1_700_000_100)
    _record(merged / "understanding/paid/c__r1.json", "paid", {"input": 10, "output": 0}, "t5")

    models = {"paid": ModelSpec(name="paid", backend="claude", vendor="v", model="m-1", can=frozenset({"text"}),
                                options={"price": PRICE})}
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
