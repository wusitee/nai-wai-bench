"""Agents that speak the Agent Client Protocol (JSON-RPC over stdio): Antigravity, DeepSeek
harness, Kimi, and others. Tool permission requests are rejected for text/vision prompts and
approved for image generation; every tool call is recorded in the response metadata."""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from nwb.backends import BackendError, Request, Response, audit_calls, image_instruction
from nwb.config import ModelSpec
from nwb.util import IMAGE_SUFFIXES, expand, media_type

PROTOCOL_VERSION = 1
_PATH_RE = re.compile(r"(/[^\"'\s]+\.(?:png|jpe?g|webp))", re.I)
_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


class AcpConnection:
    def __init__(self, command: list[str], env: dict, cwd: str, allow_tools: bool, stderr):
        self.allow_tools = allow_tools
        self.updates: list[dict] = []
        self.permissions: list[dict] = []
        self._pending: dict[int, list] = {}
        self._next_id = 0
        self._expired = False
        self.agent_info: dict = {}
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                      cwd=cwd, env=env, text=True, encoding="utf-8", bufsize=1)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _send(self, obj: dict) -> None:
        with self._lock:
            self._proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float) -> dict:
        with self._lock:
            self._next_id += 1
            rid = self._next_id
            slot = self._pending[rid] = [threading.Event(), None]
        # The watchdog bounds the write as well as the wait: a large prompt (base64 images) blocks on a
        # full pipe if the agent stops reading, and killing the agent unblocks it.
        watchdog = threading.Timer(timeout, self._expire)
        watchdog.start()
        try:
            try:
                self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            except OSError:
                pass  # the agent exited or was killed; reported below
            answered = slot[0].wait(timeout)
        finally:
            watchdog.cancel()
        msg = self._pending.pop(rid)[1]
        if msg is None:
            if not answered or self._expired:
                raise BackendError(f"ACP {method} timed out after {timeout}s")
            raise BackendError(f"ACP agent exited during {method}")
        if "error" in msg:
            raise BackendError(f"ACP {method} failed: {json.dumps(msg['error'], ensure_ascii=False)[:800]}")
        return msg.get("result") or {}

    def _expire(self) -> None:
        self._expired = True
        self._proc.kill()

    def _read(self) -> None:
        try:
            for line in self._proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "method" not in msg:
                    slot = self._pending.get(msg.get("id"))
                    if slot:
                        slot[1] = msg
                        slot[0].set()
                elif "id" in msg:
                    self._answer(msg)
                elif msg["method"] == "session/update":
                    self.updates.append(msg.get("params", {}).get("update", {}))
        except (OSError, ValueError):
            pass  # the agent was killed mid-read or its pipe closed
        finally:
            for slot in list(self._pending.values()):
                slot[0].set()

    def _answer(self, msg: dict) -> None:
        try:
            self._send(self._reply(msg))
        except OSError:
            pass  # the agent is gone; the pending request reports it

    def _reply(self, msg: dict) -> dict:
        if msg["method"] != "session/request_permission":
            return {"jsonrpc": "2.0", "id": msg["id"],
                    "error": {"code": -32601, "message": f"{msg['method']} is not supported"}}
        params = msg.get("params", {})
        options = params.get("options", [])
        prefix = "allow" if self.allow_tools else "reject"
        choice = next((o for o in options if o.get("kind") == f"{prefix}_once"), None) or \
            next((o for o in options if o.get("kind", "").startswith(prefix)), None)
        self.permissions.append({"tool": (params.get("toolCall") or {}).get("title"),
                                 "decision": choice.get("kind") if choice else "cancelled"})
        outcome = {"outcome": "selected", "optionId": choice["optionId"]} if choice else {"outcome": "cancelled"}
        return {"jsonrpc": "2.0", "id": msg["id"], "result": {"outcome": outcome}}

    def close(self) -> None:
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        self._proc.terminate()
        try:
            self._proc.wait(10)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class AcpBackend:
    def __init__(self, spec: ModelSpec):
        self.spec = spec
        self.timeout = spec.options.get("timeout", 600)

    def _command_and_env(self) -> tuple[list[str], dict]:
        try:
            command = [expand(c) for c in self.spec.options["command"]]
            extra = {k: expand(v) for k, v in self.spec.options.get("env", {}).items()}
        except RuntimeError as e:
            raise BackendError(f"model {self.spec.name}: {e}") from e
        if shutil.which(command[0]) is None:
            raise BackendError(f"model {self.spec.name}: command not found: {command[0]}")
        return command, {**os.environ, **extra}

    def run(self, req: Request) -> Response:
        gen = req.image_out is not None
        command, env = self._command_and_env()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="nwb-acp-") as cwd, \
                tempfile.TemporaryFile("w+", encoding="utf-8") as stderr:
            conn = AcpConnection(command, env, cwd, allow_tools=gen, stderr=stderr)
            try:
                result = self._session(conn, cwd, req, gen)
            except BackendError as e:
                stderr.seek(0)
                tail = stderr.read()[-600:].strip()
                raise BackendError(f"{e}{' | stderr: ' + tail if tail else ''}") from e
            finally:
                conn.close()
            text, tool_calls, inline = summarize(conn.updates)
            resp = Response(text=text, meta={
                "backend": "acp", "model": self.spec.model, "stop_reason": result.get("stopReason"),
                "client": " ".join(str(conn.agent_info[k]) for k in ("name", "version") if conn.agent_info.get(k)) or None,
                "seconds": round(time.monotonic() - started, 1),
                "tools_used": [c.get("title") or c.get("kind") or "tool" for c in tool_calls],
                "tool_calls": [compact(c) for c in tool_calls], "permissions": conn.permissions,
            })
            if gen:
                inputs = {hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in req.images}
                resp.images = collect_images(inline, tool_calls, Path(cwd), req.image_out, exclude=inputs)
                image_calls = [c for c in tool_calls if "image" in f"{c.get('title', '')} {c.get('kind', '')}".lower()]
                sent = [c["rawInput"].get("prompt") if isinstance(c.get("rawInput"), dict) else None
                        for c in image_calls]
                raw = [json.dumps(c.get("rawInput"), ensure_ascii=False) for c in image_calls]
                resp.meta["audit"] = audit_calls(sent, raw, req.prompt)
                if not resp.images:
                    raise BackendError(f"agent produced no image: {text[:300]}")
        return resp

    def _session(self, conn: AcpConnection, cwd: str, req: Request, gen: bool) -> dict:
        init = conn.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
        }, 120)
        conn.agent_info = init.get("agentInfo") or {}
        if req.images and not init.get("agentCapabilities", {}).get("promptCapabilities", {}).get("image"):
            raise BackendError(f"model {self.spec.name}: agent does not accept image input")
        if auth := self.spec.options.get("auth"):
            conn.request("authenticate", {"methodId": auth}, 300)
        session = conn.request("session/new", {"cwd": cwd, "mcpServers": []}, 120)
        sid = session["sessionId"]
        self._configure(conn, sid, session)

        prompt = req.prompt
        if gen:
            hint = f" Save the generated image file into {cwd}."
            prompt = image_instruction(req.prompt, bool(req.images), "image generation", hint)
        blocks = [{"type": "image", "mimeType": media_type(Path(p)),
                   "data": base64.b64encode(Path(p).read_bytes()).decode()} for p in req.images]
        blocks.append({"type": "text", "text": prompt})
        return conn.request("session/prompt", {"sessionId": sid, "prompt": blocks}, self.timeout)

    def _configure(self, conn: AcpConnection, sid: str, session: dict) -> None:
        wanted = dict(self.spec.options.get("config", {}))
        if self.spec.model:
            wanted = {"model": self.spec.model, **wanted}
        options = session.get("configOptions") or []
        for cid, value in wanted.items():
            opt = next((o for o in options if o.get("id") == cid), None)
            if opt is None and cid == "model":
                opt = next((o for o in options if o.get("category") == "model"), None)
            if opt is None:
                if cid == "model" and session.get("models"):
                    available = [m.get("modelId") for m in session["models"].get("availableModels", [])]
                    if value not in available:
                        raise BackendError(f"model {value!r} not offered; available: {available}")
                    conn.request("session/set_model", {"sessionId": sid, "modelId": value}, 60)
                    continue
                raise BackendError(f"agent has no config option {cid!r}")
            values = option_values(opt.get("options", []))
            if value not in values:
                raise BackendError(f"{cid}={value!r} not offered; available: {values}")
            if opt.get("currentValue") != value:
                conn.request("session/set_config_option", {"sessionId": sid, "configId": opt["id"], "value": value}, 60)


def option_values(options: list) -> list:
    values = []
    for o in options:
        if "options" in o:
            values += option_values(o["options"])
        elif "value" in o:
            values.append(o["value"])
    return values


def summarize(updates: list[dict]) -> tuple[str, list[dict], list[dict]]:
    """Fold session/update notifications into reply text, tool calls, and inline image blocks."""
    text, tools, inline = [], {}, []
    for u in updates:
        kind = u.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = u.get("content", {})
            if content.get("type") == "text":
                text.append(content.get("text", ""))
            elif content.get("type") == "image":
                inline.append(content)
        elif kind in ("tool_call", "tool_call_update"):
            call = tools.setdefault(u.get("toolCallId"), {})
            for key in ("title", "kind", "status", "rawInput", "rawOutput", "locations"):
                if u.get(key) is not None:
                    call[key] = u[key]
            for c in u.get("content") or []:
                inner = c.get("content") if c.get("type") == "content" else None
                if inner and inner.get("type") == "image":
                    inline.append(inner)
    return "".join(text), list(tools.values()), inline


def compact(call: dict) -> dict:
    """Tool call record for result metadata, with bulky inputs/outputs truncated."""
    out = {k: call[k] for k in ("title", "kind", "status") if k in call}
    if "rawInput" in call:
        out["rawInput"] = json.dumps(call["rawInput"], ensure_ascii=False)[:1000]
    return out


def collect_images(inline: list[dict], tool_calls: list[dict], cwd: Path, out_dir: Path,
                   exclude: set[str] = frozenset()) -> list[Path]:
    """Save images returned inline, written to the session directory, or referenced by tool calls,
    skipping duplicates (agents often return the same image inline and as a file) and any image whose
    SHA-256 is in `exclude` (the input images, which agents may copy and reference)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved, seen = [], set(exclude)

    def keep(data: bytes, name: str) -> None:
        digest = hashlib.sha256(data).hexdigest()
        if digest not in seen:
            seen.add(digest)
            dst, n = out_dir / name, 1
            while dst.exists():  # distinct images can share a file name
                dst = out_dir / f"{Path(name).stem}-{n}{Path(name).suffix}"
                n += 1
            dst.write_bytes(data)
            saved.append(dst)

    for i, block in enumerate(inline):
        keep(base64.b64decode(block["data"]), f"inline-{i}{_EXT.get(block.get('mimeType'), '.png')}")
    files = [p for p in cwd.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES]
    files += [Path(m) for m in _PATH_RE.findall(json.dumps(tool_calls, ensure_ascii=False))]
    for src in files:
        if src.is_file():
            keep(src.read_bytes(), src.name)
    return saved
