"""Models behind an OpenAI-compatible Chat Completions API (e.g. Xiaomi MiMo). This is a plain model
call with no agent harness and no tools; credentials come from an environment variable or a CC Switch
provider entry."""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from nwb.backends import BackendError, Request, Response, neutral_inputs, tokens
from nwb.backends.cc_switch import openai_credentials
from nwb.config import ModelSpec
from nwb.util import media_type

SYSTEM_PROMPT = "You are a helpful assistant."
RETRY_STATUS = {429, 500, 502, 503, 504}
RETRIES = 3


class OpenAICompatBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.timeout = spec.options.get("timeout", 600)

    def _endpoint(self) -> tuple[str, str]:
        opts = self.spec.options
        base, key = None, None
        if provider := opts.get("cc_switch"):
            base, key = openai_credentials(provider)
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
