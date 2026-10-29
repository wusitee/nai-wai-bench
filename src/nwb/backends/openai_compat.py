"""Models behind an OpenAI-compatible Chat Completions API (e.g. Xiaomi MiMo). This is a plain model
call with no agent harness and no tools; credentials come from an environment variable or a CC Switch
provider entry."""

import base64
import json
import os
import sqlite3
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nwb.backends import BackendError, Request, Response, neutral_inputs, tokens
from nwb.config import ModelSpec
from nwb.util import media_type

SYSTEM_PROMPT = "You are a helpful assistant."
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 3


def cc_switch_credentials(provider: str, db_path: Path | None = None) -> tuple[str, str]:
    """(base_url, api_key) of a CC Switch provider's OpenAI-compatible endpoint, read from its pi or
    codex configuration in CC Switch's database (CC_SWITCH_DB, default ~/.cc-switch/cc-switch.db)."""
    db = db_path or Path(os.environ.get("CC_SWITCH_DB", "~/.cc-switch/cc-switch.db")).expanduser()
    if not db.is_file():
        raise BackendError(f"CC Switch database not found: {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("select app_type, settings_config from providers where name = ?", (provider,)).fetchall()
    finally:
        con.close()
    for app, raw in rows:
        cfg = json.loads(raw)
        if app == "pi" and cfg.get("baseUrl") and cfg.get("apiKey"):
            return cfg["baseUrl"], cfg["apiKey"]
        if app == "codex" and (key := cfg.get("auth", {}).get("OPENAI_API_KEY")):
            providers = tomllib.loads(cfg.get("config", "")).get("model_providers", {})
            base = next((p["base_url"] for p in providers.values() if p.get("base_url")), None)
            if base:
                return base, key
    if not rows:
        raise BackendError(f"no CC Switch provider named {provider!r}")
    raise BackendError(f"CC Switch provider {provider!r} has no OpenAI-compatible (pi or codex) configuration")


class OpenAICompatBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.timeout = spec.options.get("timeout", 600)

    def _endpoint(self) -> tuple[str, str]:
        opts = self.spec.options
        base, key = None, None
        if provider := opts.get("cc_switch"):
            base, key = cc_switch_credentials(provider)
        base = opts.get("base_url", base)
        if env := opts.get("api_key_env"):
            key = os.environ.get(env) or key
        if not base or not key:
            raise BackendError(f"model {self.spec.name}: set base_url and api_key_env, or cc_switch")
        return base.rstrip("/"), key

    @neutral_inputs
    def run(self, req: Request) -> Response:
        if req.image_out is not None:
            raise BackendError("the openai backend cannot generate images")
        if self.spec.options.get("effort", "default") != "default":
            raise BackendError("openai backend has no supported graded effort control; use effort=default")
        base, key = self._endpoint()
        content = [{"type": "text", "text": req.prompt}]
        content += [{"type": "image_url", "image_url": {
            "url": f"data:{media_type(Path(p))};base64,{base64.b64encode(Path(p).read_bytes()).decode()}"}}
            for p in req.images]
        body = json.dumps({"model": self.spec.model, "messages": [
            {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": content}]}).encode()
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        started = time.monotonic()
        for attempt in range(RETRIES + 1):
            try:
                request = urllib.request.Request(f"{base}/chat/completions", data=body, headers=headers)
                with urllib.request.urlopen(request, timeout=self.timeout) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                detail = e.read()[:500].decode(errors="replace")
                if e.code not in RETRY_STATUS or attempt == RETRIES:
                    raise BackendError(f"HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == RETRIES:
                    raise BackendError(f"request failed: {e}") from e
            time.sleep(5 * 2 ** attempt)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise BackendError(f"unexpected response: {json.dumps(data)[:500]}") from e
        return Response(text=message.get("content") or "", meta={
            "backend": "openai", "model": self.spec.model, "client": urllib.parse.urlsplit(base).hostname,
            "seconds": round(time.monotonic() - started, 1),
            "tools_used": [], "usage": data.get("usage"),
            "tokens": tokens("openai", data.get("usage")), "resolved_model": data.get("model"),
            "cost_usd_reported": None,
        })
