"""The sandbox runner (runner/runner.py) on its own: how it reads each CLI's output, how it talks to
Agent Town when the network is flaky, and how it keeps the API from thinking it died mid-turn."""

import io
import json
import urllib.error

import pytest

from .conftest import load_runner

CLAUDE_LINES = [
    {"type": "system", "subtype": "init", "session_id": "s-1"},
    {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "name": "Read", "input": {"file_path": "notes.md"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": [{"type": "text", "text": "hi"}], "is_error": False}]}},
    {"type": "assistant", "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "(an error, not a reply)"}]}},
    {"type": "assistant", "message": {"model": "claude-sonnet-5-5", "content": [{"type": "text", "text": "Done: hi."}]}},
    {"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.01, "duration_ms": 1200, "num_turns": 2, "session_id": "s-1"},
]

CODEX_LINES = [
    {"type": "thread.started", "thread_id": "t-1"},
    {"type": "item.started", "item": {"type": "mcp_tool_call", "server": "gmail", "tool": "search_emails", "arguments": {"q": "x"}}},
    {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "gmail", "tool": "search_emails", "status": "completed", "result": "3 emails"}},
    {"type": "item.started", "item": {"type": "command_execution", "command": "ls"}},
    {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "aggregated_output": "a\nb", "exit_code": 0}},
    {"type": "item.completed", "item": {"type": "agent_message", "text": "Two files."}},
    {"type": "turn.completed", "usage": {"input_tokens": 10}},
]


def engines(tmp_path, monkeypatch, lines):
    runner = load_runner(tmp_path, monkeypatch)
    emitted = []
    monkeypatch.setattr(runner, "emit", lambda kind, **data: emitted.append((kind, data)))
    monkeypatch.setattr(runner, "system_prompt", lambda *a: "sys")

    def fake_stream(cmd, prompt, env, on_line):
        runner.parse_lines([json.dumps(x) for x in lines] + ["not json", ""], on_line)
        return 0, ""
    monkeypatch.setattr(runner, "stream", fake_stream)
    return runner, emitted


M = {"agent": {"name": "A", "description": ""}, "instructions": "hi", "tools": [], "team": [], "shared": [], "public": []}
CRED = {"kind": "api_key", "secret": "k", "model": "", "thinking": ""}


def test_claude_stream_json_becomes_events(tmp_path, monkeypatch):
    runner, emitted = engines(tmp_path, monkeypatch, CLAUDE_LINES)
    c = runner.Claude(M, CRED, {}, [])
    c.turn("hi")
    assert c.session == "s-1"                                      # resumed next turn
    assert emitted == [
        ("text", {"text": "Let me look."}),
        ("tool", {"name": "Read", "input": '{"file_path": "notes.md"}'}),
        ("tool_result", {"output": "hi", "is_error": False}),
        ("text", {"text": "Done: hi."}),                            # the synthetic message is skipped
        ("done", {"ok": True, "cost_usd": 0.01, "duration_ms": 1200, "turns": 2, "auth_failed": False}),
    ]


def test_claude_result_errors_are_reported(tmp_path, monkeypatch):
    bad = [{"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "401 invalid x-api-key", "api_error_status": 401}]
    runner, emitted = engines(tmp_path, monkeypatch, bad)
    runner.Claude(M, CRED, {}, []).turn("hi")
    assert emitted[0] == ("error", {"detail": "401 invalid x-api-key"})
    assert emitted[1][0] == "done" and emitted[1][1]["ok"] is False and emitted[1][1]["auth_failed"] is True


def test_a_turn_with_no_result_line_is_an_error(tmp_path, monkeypatch):
    runner, emitted = engines(tmp_path, monkeypatch, [{"type": "system", "session_id": "s"}])
    runner.Claude(M, CRED, {}, []).turn("hi")
    assert emitted[0][0] == "error" and "exited with 0" in emitted[0][1]["detail"]
    assert emitted[1] == ("done", {"ok": False})


def test_codex_exec_json_becomes_events(tmp_path, monkeypatch):
    runner, emitted = engines(tmp_path, monkeypatch, CODEX_LINES)
    c = runner.Codex(M, CRED, {}, [])
    c.turn("hi")
    assert c.thread == "t-1"
    assert emitted == [
        ("tool", {"name": "gmail.search_emails", "input": '{"q": "x"}'}),
        ("tool_result", {"output": "3 emails", "is_error": False}),
        ("tool", {"name": "shell", "input": "ls"}),
        ("tool_result", {"output": "a\nb", "is_error": False}),
        ("text", {"text": "Two files."}),
        ("done", {"ok": True, "usage": {"input_tokens": 10}}),
    ]


def test_codex_turn_failed(tmp_path, monkeypatch):
    runner, emitted = engines(tmp_path, monkeypatch, [{"type": "turn.failed", "error": {"message": "401 Unauthorized: bad key"}}])
    runner.Codex(M, CRED, {}, []).turn("hi")
    assert emitted == [("error", {"detail": "401 Unauthorized: bad key"}), ("done", {"ok": False, "auth_failed": True})]


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def test_api_retries_network_trouble_but_not_the_runs_end(tmp_path, monkeypatch):
    runner = load_runner(tmp_path, monkeypatch)
    monkeypatch.setattr(runner.time, "sleep", lambda s: None)
    calls = []

    def flaky(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.URLError("tunnel down")
        if len(calls) == 2:
            raise urllib.error.HTTPError(req.full_url, 502, "bad gateway", {}, None)
        return Response(b'{"ok": true}')
    monkeypatch.setattr(runner.urllib.request, "urlopen", flaky)
    assert runner.api("GET", "/api/runtime/ping") == {"ok": True} and len(calls) == 3

    def ended(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "gone", {}, None)
    monkeypatch.setattr(runner.urllib.request, "urlopen", ended)
    with pytest.raises(runner.Ended):
        runner.api("GET", "/api/runtime/inbox")

    def bad_request(req, timeout):
        calls.append("422")
        raise urllib.error.HTTPError(req.full_url, 422, "no", {}, None)
    monkeypatch.setattr(runner.urllib.request, "urlopen", bad_request)
    calls.clear()
    with pytest.raises(urllib.error.HTTPError):
        runner.api("PUT", "/api/runtime/memory", {"content": "x"})
    assert calls == ["422"]                                       # a 4xx isn't retried


def test_stream_drains_stderr_and_pings_while_it_runs(tmp_path, monkeypatch):
    """A CLI that floods stderr used to wedge the pipe; and the heartbeat runs while stdout is read."""
    runner = load_runner(tmp_path, monkeypatch)
    pings = []
    monkeypatch.setattr(runner, "api", lambda m, p, b=None: pings.append(p) or {})
    monkeypatch.setattr(runner, "HEARTBEAT", 0.05)
    import sys
    script = ("import sys, time\n"
              "sys.stdin.read()\n"
              "sys.stderr.write('noise\\n' * 50000)\n"
              "sys.stdout.write('{\"type\": \"x\"}\\n')\n"
              "sys.stdout.flush(); time.sleep(0.2)\n")
    seen = []
    code, err = runner.stream([sys.executable, "-c", script], "prompt", {}, seen.append)
    assert code == 0 and seen == [{"type": "x"}] and err.endswith("noise\n") and len(err) <= 2000
    assert "/api/runtime/ping" in pings
