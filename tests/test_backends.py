import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from nwb.backends import BackendError, Request
from nwb.backends.acp import AcpBackend, AcpConnection
from nwb.backends.codex import audit_rollout
from nwb.backends.openai_compat import OpenAICompatBackend, cc_switch_credentials
from nwb.config import ModelSpec

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


def acp_backend() -> AcpBackend:
    spec = ModelSpec(name="fake", backend="acp", vendor="test", model="b", can=frozenset({"text", "image"}),
                     options={"command": [sys.executable, str(FAKE_AGENT)], "timeout": 30})
    return AcpBackend(spec)


def test_acp_text_prompt_selects_model_rejects_tools_and_records_them():
    resp = acp_backend().run(Request(prompt="hello"))
    assert resp.text == "model=b permission=no"
    assert resp.meta["tools_used"] == ["web_search"]
    assert resp.meta["permissions"] == [{"tool": "web_search", "decision": "reject_once"}]


def test_acp_image_generation_allows_tools_and_saves_each_image_once(tmp_path):
    resp = acp_backend().run(Request(prompt="IMAGE please", image_out=tmp_path / "out"))
    assert resp.meta["permissions"][0]["decision"] == "allow_once"
    assert len(resp.images) == 1
    assert resp.images[0].read_bytes().startswith(b"\x89PNG")


def _rollout(tmp_path: Path, *inputs: str) -> Path:
    path = tmp_path / "rollout.jsonl"
    lines = [{"type": "response_item", "payload": {"type": "message", "content": "hi"}}]
    lines += [{"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": i}}
              for i in inputs]
    path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines), encoding="utf-8")
    return path


def test_codex_audit_requires_the_exact_prompt(tmp_path):
    prompt = "参考这张图，画一个同样风格的猫版本"
    call = f'const r = await tools.image_gen__imagegen({{prompt:{json.dumps(prompt)},num_last_images_to_include:1}});'
    audit = audit_rollout(_rollout(tmp_path, call), prompt)
    assert audit["image_gen_calls"] == 1 and audit["verbatim"] is True and audit["refused"] is False

    # The provider's safety rejection arrives in the tool output and is a scored refusal, not a retry.
    rollout = _rollout(tmp_path, call)
    blocked = {"type": "custom_tool_call_output", "output": [{"type": "input_text", "text":
               'image generation failed: http 400: {"error": {"code": "moderation_blocked"}}'}]}
    rollout.write_text(rollout.read_text() + "\n" + json.dumps({"type": "response_item", "payload": blocked}))
    assert audit_rollout(rollout, prompt)["refused"] is True

    # Extra description appended to a name-only prompt must not pass as verbatim.
    appended = f'await tools.image_gen__imagegen({{prompt:{json.dumps(prompt + "，黄色胖身体，捧腹大笑")}}});'
    audit = audit_rollout(_rollout(tmp_path, call, appended), prompt)
    assert audit["image_gen_calls"] == 2 and audit["verbatim"] is False

    assert audit_rollout(None, prompt)["verbatim"] is None


def test_acp_request_times_out_when_agent_stops_reading():
    # The agent never reads stdin, so a large prompt blocks on the full pipe; the timeout must still fire.
    conn = AcpConnection([sys.executable, "-c", "import time; time.sleep(30)"], dict(os.environ),
                         os.getcwd(), allow_tools=False, stderr=subprocess.DEVNULL)
    started = time.monotonic()
    try:
        with pytest.raises(BackendError, match="timed out"):
            conn.request("session/prompt", {"data": "x" * 2_000_000}, timeout=1)
    finally:
        conn.close()
    assert time.monotonic() - started < 10


def test_openai_backend_sends_system_prompt_and_inline_images(tmp_path, monkeypatch):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"], seen["auth"] = self.path, self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = json.dumps({"choices": [{"message": {"content": "奶龙"}}], "usage": {"total_tokens": 3}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply.encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNG fake")
    monkeypatch.setenv("TEST_KEY", "secret")
    spec = ModelSpec(name="m", backend="openai", vendor="v", model="mimo", can=frozenset({"text", "vision"}),
                     options={"base_url": f"http://127.0.0.1:{server.server_port}/v1/", "api_key_env": "TEST_KEY"})
    try:
        resp = OpenAICompatBackend(spec).run(Request(prompt="这是谁？", images=[image]))
    finally:
        server.shutdown()
    assert resp.text == "奶龙" and resp.meta["tools_used"] == []
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer secret"
    system, user = seen["body"]["messages"]
    assert seen["body"]["model"] == "mimo" and system["role"] == "system"
    assert user["content"][0] == {"type": "text", "text": "这是谁？"}
    assert user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_cc_switch_credentials_from_pi_or_codex_provider(tmp_path):
    db = tmp_path / "cc-switch.db"
    con = sqlite3.connect(db)
    con.execute("create table providers (name text, app_type text, settings_config text)")
    con.execute("insert into providers values (?, ?, ?)", ("Pi P", "pi", json.dumps(
        {"baseUrl": "https://pi.example/v1", "apiKey": "k1"})))
    con.execute("insert into providers values (?, ?, ?)", ("Codex P", "claude", json.dumps({"env": {}})))
    con.execute("insert into providers values (?, ?, ?)", ("Codex P", "codex", json.dumps({
        "auth": {"OPENAI_API_KEY": "k2"},
        "config": 'model = "m"\n[model_providers.custom]\nbase_url = "https://codex.example/v1"\n'})))
    con.commit()
    con.close()
    assert cc_switch_credentials("Pi P", db) == ("https://pi.example/v1", "k1")
    assert cc_switch_credentials("Codex P", db) == ("https://codex.example/v1", "k2")
