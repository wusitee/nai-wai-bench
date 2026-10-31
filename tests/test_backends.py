import base64
import json
import os
import sqlite3
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path

import pytest

from nwb.backends import BackendError, Request, tokens
from nwb.backends.acp import AcpBackend, AcpConnection, acp_usage
from nwb.backends.codex import CodexBackend, ISOLATED_FEATURES, audit_rollout, recorded_tool_profile
from nwb.backends.claude import ClaudeBackend
from nwb.backends.openai_compat import OpenAICompatBackend, cc_switch_credentials
from nwb.config import ModelSpec, model_settings

FAKE_AGENT = Path(__file__).with_name("fake_acp_agent.py")


def test_codex_versioned_tool_profiles_control_and_record_isolation(tmp_path):
    from dataclasses import replace

    spec = ModelSpec("m", "codex", "openai", "m", frozenset({"text", "vision"}), {"effort": "high"})
    legacy, legacy_id = model_settings(spec, tmp_path)
    isolated = replace(spec, options={**spec.options, "tool_profile": "isolated-v1"})
    settings, isolated_id = model_settings(isolated, tmp_path)
    assert recorded_tool_profile(legacy["command"]) == "legacy-v1"
    assert recorded_tool_profile(settings["command"]) == "isolated-v1" and isolated_id != legacy_id
    assert settings["command"] == legacy["command"] + [arg for feature in ISOLATED_FEATURES for arg in ("--disable", feature)]
    assert recorded_tool_profile(settings["command"] + ["--disable", "another_feature"]) == "custom"
    assert CodexBackend(isolated).command([], True) == CodexBackend(spec).command([], True)
    with pytest.raises(ValueError, match="unknown Codex tool_profile"):
        CodexBackend(replace(spec, options={"tool_profile": "unknown"})).command([], False)


def acp_backend(**options) -> AcpBackend:
    spec = ModelSpec(name="fake", backend="acp", vendor="test", model="b", can=frozenset({"text", "image"}),
                     options={"command": [sys.executable, str(FAKE_AGENT)], "timeout": 30, **options})
    return AcpBackend(spec)


def test_acp_text_prompt_selects_model_rejects_tools_and_records_them():
    resp = acp_backend(effort="high").run(Request(prompt="hello"))
    assert resp.text == "model=b permission=no"
    assert resp.meta["session_config"] == {"model": "b", "thinking": "high"}
    assert resp.meta["resolved_model"] == "b"
    assert resp.meta["tokens"] == {"input": 20, "output": 10, "reasoning": 4, "cached_input": 3, "cache_write": None}
    assert resp.meta["tools_used"] == ["web_search"]
    assert resp.meta["permissions"] == [{"tool": "web_search", "decision": "reject_once"}]


@pytest.mark.parametrize("changed_format", [False, True])
def test_acp_usage_command_is_separate_from_answer_and_unknown_counts_stay_null(changed_format):
    env = {"FAKE_NO_USAGE": "1", **({"FAKE_USAGE_FORMAT": "1"} if changed_format else {})}
    resp = acp_backend(effort="high", usage_command="/usage", env=env).run(Request("hello"))
    assert resp.text == "model=b permission=no"
    assert resp.meta["usage"] is None  # The local command does not replace raw protocol usage.
    assert resp.meta["tokens"] == {"input": None if changed_format else 20,
                                   "output": None if changed_format else 10,
                                   "reasoning": None, "cached_input": None, "cache_write": None}
    if changed_format:
        assert resp.meta["usage_command"]["error"] == "unrecognized session token totals"
        assert "tokens_source" not in resp.meta
    else:
        assert resp.meta["tokens_source"] == "usage-command"


def test_acp_image_generation_allows_tools_and_saves_each_image_once(tmp_path):
    source = tmp_path / "semantic-model-run-name.png"
    source.write_bytes(b"input image")
    resp = acp_backend().run(Request(prompt="IMAGE please", images=[source], image_out=tmp_path / "out"))
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


@pytest.mark.parametrize("credentials", ["", "user:password@"])
def test_openai_backend_sends_system_prompt_and_inline_images(tmp_path, monkeypatch, credentials):
    seen = {}

    def urlopen(request, timeout):
        seen["path"], seen["auth"] = request.full_url, request.get_header("Authorization")
        seen["body"] = json.loads(request.data)
        return BytesIO(json.dumps({"model": "resolved", "choices": [{"message": {"content": "奶龙"}}],
                                 "usage": {"prompt_tokens": 20, "completion_tokens": 10,
                                           "prompt_tokens_details": {"cached_tokens": 4},
                                           "completion_tokens_details": {"reasoning_tokens": 6}}}).encode())

    monkeypatch.setattr("nwb.backends.openai_compat.urllib.request.urlopen", urlopen)
    staged = []
    from nwb.util import media_type
    monkeypatch.setattr("nwb.backends.openai_compat.media_type", lambda p: staged.append(p) or media_type(p))
    image = tmp_path / "x.png"
    image.write_bytes(b"\x89PNG fake")
    monkeypatch.setenv("TEST_KEY", "secret")
    spec = ModelSpec(name="m", backend="openai", vendor="v", model="mimo", can=frozenset({"text", "vision"}),
                     options={"base_url": f"https://{credentials}example.test/v1/", "api_key_env": "TEST_KEY"})
    resp = OpenAICompatBackend(spec).run(Request(prompt="这是谁？", images=[image]))
    assert staged[0].name == "image-1.png" and not staged[0].exists()
    assert resp.meta["resolved_model"] == "resolved"
    assert resp.meta["client"] == "example.test"
    assert resp.meta["tokens"] == {"input": 20, "cached_input": 4, "cache_write": None, "output": 10, "reasoning": 6}
    assert resp.text == "奶龙" and resp.meta["tools_used"] == []
    assert seen["path"] == f"https://{credentials}example.test/v1/chat/completions" and seen["auth"] == "Bearer secret"
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


def test_acp_rejects_unavailable_or_unconfirmed_effort():
    for options, error in [({"effort": "max"}, "not offered"),
                           ({"effort": "high", "effort_option": "missing"}, "no config option"),
                           ({"effort": "high", "env": {"FAKE_IGNORE_EFFORT": "1"}}, "did not confirm"),
                           ({"effort": "high", "effort_source": "model-id"}, "does not match"),
                           ({"usage_command": "/not-a-command"}, "not advertised")]:
        with pytest.raises(BackendError, match=error):
            acp_backend(**options).run(Request("hello"))

    spec = ModelSpec("m", "openai", "v", "m", frozenset({"text"}), {"effort": "high"})
    with pytest.raises(BackendError, match="no supported graded effort"):
        OpenAICompatBackend(spec).run(Request("hello"))


def test_acp_image_blocks_have_no_path_uri_or_name(tmp_path):
    source = tmp_path / "nailong-semantic.png"
    source.write_bytes(b"image")
    second = tmp_path / "another-semantic.jpg"
    second.write_bytes(b"second")
    resp = acp_backend().run(Request("INSPECT", [source, second]))
    wire = json.loads(resp.text)
    assert Path(wire["cwd"]) != Path.cwd() and not Path(wire["cwd"]).exists()
    block = wire["blocks"][0]
    assert set(block) == {"type", "mimeType", "data"}
    assert str(source) not in resp.text and source.name not in resp.text
    assert [base64.b64decode(b["data"]) for b in wire["blocks"] if b["type"] == "image"] == [b"image", b"second"]


@pytest.mark.parametrize("backend", ["codex", "claude"])
def test_cli_stages_attachments_and_records_usage(tmp_path, monkeypatch, backend):
    from types import SimpleNamespace
    source = tmp_path / "runs-model-stimulus.png"
    source.write_bytes(b"image")
    spec = ModelSpec("m", backend, "v", "requested", frozenset({"vision"}), {"effort": "high"})
    second = tmp_path / "another-model-name.jpg"
    second.write_bytes(b"second")
    paths = []
    if backend == "claude":
        from nwb.util import media_type
        monkeypatch.setattr("nwb.backends.claude.media_type", lambda p: paths.append(p) or media_type(p))

    monkeypatch.setattr("nwb.backends.shutil.which", lambda name: f"/opt/bin/{name}.cmd")

    def run(command, **kwargs):
        assert Path(kwargs["cwd"]) != Path.cwd()
        assert command[0] == f"/opt/bin/{backend}.cmd" and kwargs["encoding"] == "utf-8"
        assert str(source) not in str(command) + kwargs["input"]
        if backend == "codex":
            paths.extend(Path(command[i + 1]) for i, value in enumerate(command) if value == "--image")
            assert 'model_reasoning_effort="high"' in command
            events = [{"type": "thread.started", "thread_id": "s"},
                      {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
                      {"type": "turn.completed", "usage": {"input_tokens": 100, "cached_input_tokens": 20,
                                                              "output_tokens": 29, "reasoning_output_tokens": 14}}]
        else:
            assert command[command.index("--effort") + 1] == "high"
            content = json.loads(kwargs["input"])["message"]["content"]
            assert set(content[0]["source"]) == {"type", "media_type", "data"}
            events = [{"type": "result", "result": "OK", "total_cost_usd": 0.25,
                       "modelUsage": {"resolved": {}}, "usage": {"input_tokens": 10,
                        "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30, "output_tokens": 40}}]
        assert [p.name for p in paths] == ["image-1.png", "image-2.jpg"]
        assert [p.read_bytes() for p in paths] == [b"image", b"second"]
        return SimpleNamespace(stdout="\n".join(json.dumps(e) for e in events), stderr="", returncode=0)

    monkeypatch.setattr(f"nwb.backends.{backend}.subprocess.run", run)
    monkeypatch.setattr(f"nwb.backends.{backend}.cli_version", lambda _: "test")
    resp = (CodexBackend if backend == "codex" else ClaudeBackend)(spec).run(Request("hello", [source, second]))
    assert resp.text == "OK" and all(not p.exists() for p in paths)
    if backend == "codex":
        assert resp.meta["tokens"]["output"] == 29 and resp.meta["tokens"]["reasoning"] == 14
    else:
        assert resp.meta["tokens"]["input"] == 60 and resp.meta["tokens"]["output"] == 40
        assert resp.meta["resolved_model"] == "resolved" and resp.meta["cost_usd_reported"] == 0.25


def test_unknown_usage_stays_null_and_acp_occupancy_is_not_token_usage():
    for backend in ("codex", "claude", "acp", "openai"):
        assert all(v is None for v in tokens(backend, None).values())
    assert tokens("claude", {"input_tokens": 12})["input"] is None
    occupancy = [{"sessionUpdate": "usage_update", "used": 42, "size": 1000}]
    assert acp_usage({}, occupancy) is None
    update = {"sessionUpdate": "usage_update", "inputTokens": 10, "outputTokens": 5}
    assert acp_usage({}, [update]) == {"inputTokens": 10, "outputTokens": 5}
    assert acp_usage({"_meta": {"usage": {"thoughtTokens": 3}}}, [update])["thoughtTokens"] == 3
    # ACP adapters can separate uncached input; the total disambiguates it from inclusive input.
    native = {"inputTokens": 30, "outputTokens": 10, "cachedReadTokens": 40,
              "cachedWriteTokens": 30, "thoughtTokens": 5, "totalTokens": 110}
    assert acp_usage(native, []) == native
    assert tokens("acp", native)["input"] == 100
    assert tokens("acp", {**native, "inputTokens": 100})["input"] == 100
    assert tokens("acp", native)["output"] == 10


def test_codex_legacy_effort_and_generation_excludes_input_copies(tmp_path):
    spec = ModelSpec("m", "codex", "v", "m", frozenset({"image"}), {"reasoning": "low"})
    backend = CodexBackend(spec)
    assert 'model_reasoning_effort="low"' in backend.command([], True)
    backend.home = tmp_path / "home"
    generated = backend.home / "generated_images/s"
    generated.mkdir(parents=True)
    source = tmp_path / "image-1.png"
    source.write_bytes(b"input")
    (generated / "copy.png").write_bytes(b"input")
    (generated / "output.png").write_bytes(b"output")
    files = backend._collect_images("s", tmp_path / "out", [source])
    assert [p.read_bytes() for p in files] == [b"output"]
