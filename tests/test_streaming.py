"""Tests for the Ollama HTTP client with a real local mock server.

We spin up an actual `http.server` on a random port and point the client
at it — that exercises the full httpx streaming path, not just the JSON
parsing. The mock returns Ollama's NDJSON wire format verbatim.
"""
from __future__ import annotations

import asyncio
import json
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from purr.ollama_client import OllamaClient, OllamaError


# ---- mock server -----------------------------------------------------------

class _MockOllamaHandler(BaseHTTPRequestHandler):
    """Hand-rolled Ollama mock. Behaviour is controlled by the per-test
    `MOCK_STATE` dict — each request reads from it and writes a response."""

    # silence the default "code 200 -" stderr noise
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:
        state = MOCK_STATE
        if self.path == "/api/tags":
            body = json.dumps({
                "models": [
                    {"name": state.get("model_name", "fake:7b")},
                    {"name": "other:1b"},
                ]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        state = MOCK_STATE
        # honour the test's chosen response behaviour
        if state.get("error_status"):
            msg = state["error_status"]
            body = b"ollama exploded"
            self.send_response(msg)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        chunks: list[dict] = state.get("chunks", [])
        delay: float = state.get("chunk_delay", 0.0)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        for i, ch in enumerate(chunks):
            payload = json.dumps(ch).encode() + b"\n"
            # write in chunked encoding
            self.wfile.write(f"{len(payload):x}\r\n".encode())
            self.wfile.write(payload)
            self.wfile.write(b"\r\n")
            self.wfile.flush()
            if delay and i < len(chunks) - 1:
                time.sleep(delay)
        # chunked terminator
        self.wfile.write(b"0\r\n\r\n")


MOCK_STATE: dict = {}


class _ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture()
def mock_ollama() -> str:
    """Start a mock Ollama on a random port; return its base URL."""
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = _ThreadingHTTPServer(("127.0.0.1", port), _MockOllamaHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


# ---- the actual tests ------------------------------------------------------

def test_list_models(mock_ollama: str) -> None:
    async def _go() -> None:
        MOCK_STATE.clear()
        MOCK_STATE["model_name"] = "qwen3:8b"
        client = OllamaClient(host=mock_ollama, timeout=5.0)
        models = await client.list_models()
        names = [m["name"] for m in models]
        assert "qwen3:8b" in names
        assert "other:1b" in names
    asyncio.run(_go())


def test_stream_chat_text_only(mock_ollama: str) -> None:
    """Three NDJSON chunks of plain text content. Client must concat them."""
    async def _go() -> None:
        MOCK_STATE.clear()
        MOCK_STATE["chunks"] = [
            {"model": "fake:7b", "message": {"role": "assistant", "content": "Hello"}, "done": False},
            {"model": "fake:7b", "message": {"role": "assistant", "content": " world"}, "done": False},
            {"model": "fake:7b", "message": {"role": "assistant", "content": "!"}, "done": True},
        ]
        client = OllamaClient(host=mock_ollama, timeout=5.0)
        out: list[dict] = []
        async for chunk in client.stream_chat(model="fake:7b", messages=[{"role": "user", "content": "hi"}]):
            out.append(chunk)
        assert len(out) == 3
        full = "".join((c.get("message") or {}).get("content", "") for c in out)
        assert full == "Hello world!"
    asyncio.run(_go())


def test_stream_chat_with_tool_call(mock_ollama: str) -> None:
    """A tool call chunk is yielded as-is so the caller can detect it."""
    async def _go() -> None:
        MOCK_STATE.clear()
        MOCK_STATE["chunks"] = [
            {
                "model": "fake:7b",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "app_status",
                                "arguments": {},
                            }
                        }
                    ],
                },
                "done": True,
            },
        ]
        client = OllamaClient(host=mock_ollama, timeout=5.0)
        out: list[dict] = []
        async for chunk in client.stream_chat(model="fake:7b", messages=[]):
            out.append(chunk)
        assert len(out) == 1
        tc = out[0]["message"]["tool_calls"][0]["function"]["name"]
        assert tc == "app_status"
    asyncio.run(_go())


def test_stream_chat_error_status_raises(mock_ollama: str) -> None:
    """A non-200 from Ollama must raise OllamaError (not silently yield nothing)."""
    async def _go() -> None:
        MOCK_STATE.clear()
        MOCK_STATE["error_status"] = 500
        client = OllamaClient(host=mock_ollama, timeout=5.0)
        with pytest.raises(OllamaError) as ei:
            async for _ in client.stream_chat(model="fake:7b", messages=[]):
                pass
        assert "500" in str(ei.value)
    asyncio.run(_go())


def test_stream_chat_empty_stream(mock_ollama: str) -> None:
    """Server immediately closes the stream with no chunks — we should
    complete cleanly with zero yields, not crash."""
    async def _go() -> None:
        MOCK_STATE.clear()
        MOCK_STATE["chunks"] = []
        client = OllamaClient(host=mock_ollama, timeout=5.0)
        out: list[dict] = []
        async for chunk in client.stream_chat(model="fake:7b", messages=[]):
            out.append(chunk)
        assert out == []
    asyncio.run(_go())


def test_health_returns_true_on_200(mock_ollama: str) -> None:
    async def _go() -> None:
        client = OllamaClient(host=mock_ollama, timeout=2.0)
        assert await client.health() is True
    asyncio.run(_go())


def test_health_returns_false_on_unreachable() -> None:
    """A bogus host must report unhealthy, not throw."""
    async def _go() -> None:
        client = OllamaClient(host="http://127.0.0.1:1", timeout=0.5)  # nothing listens here
        assert await client.health() is False
    asyncio.run(_go())
