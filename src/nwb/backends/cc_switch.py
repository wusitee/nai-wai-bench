"""Provider credentials from CC Switch's database (CC_SWITCH_DB, default ~/.cc-switch/cc-switch.db), read at
run time so keys are never copied into this repository."""

import json
import os
import sqlite3
import tomllib
from pathlib import Path

from nwb.backends import BackendError


def _configs(provider: str, db_path: Path | None) -> list[tuple[str, dict]]:
    db = db_path or Path(os.environ.get("CC_SWITCH_DB", "~/.cc-switch/cc-switch.db")).expanduser()
    if not db.is_file():
        raise BackendError(f"CC Switch database not found: {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select app_type, settings_config from providers where name = ?", (provider,)).fetchall()
    finally:
        con.close()
    if not rows:
        raise BackendError(f"no CC Switch provider named {provider!r}")
    return [(app, json.loads(raw)) for app, raw in rows]


def openai_credentials(provider: str, db_path: Path | None = None) -> tuple[str, str]:
    """(base_url, api_key) of a provider's OpenAI-compatible endpoint, from its pi or codex configuration."""
    for app, cfg in _configs(provider, db_path):
        if app == "pi" and cfg.get("baseUrl") and cfg.get("apiKey"):
            return cfg["baseUrl"], cfg["apiKey"]
        if app == "codex" and (key := cfg.get("auth", {}).get("OPENAI_API_KEY")):
            providers = tomllib.loads(cfg.get("config", "")).get("model_providers", {})
            base = next((p["base_url"] for p in providers.values() if p.get("base_url")), None)
            if base:
                return base, key
    raise BackendError(f"CC Switch provider {provider!r} has no OpenAI-compatible (pi or codex) configuration")


def claude_env(provider: str, db_path: Path | None = None) -> dict[str, str]:
    """The environment CC Switch writes into Claude Code's settings for a provider (ANTHROPIC_BASE_URL,
    ANTHROPIC_AUTH_TOKEN, model aliases, and so on)."""
    for app, cfg in _configs(provider, db_path):
        if app == "claude" and isinstance(cfg.get("env"), dict):
            return {k: str(v) for k, v in cfg["env"].items()}
    raise BackendError(f"CC Switch provider {provider!r} has no Claude Code configuration")
