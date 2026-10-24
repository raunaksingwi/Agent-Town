"""Runs inside the sandbox. Standard library only, so any image with Python can run it.

    AGENTTOWN_API_URL, AGENTTOWN_RUN_TOKEN  set by the provider (app/sandbox.py)

1. GET  /api/runtime/setup     the manifest, the owner's model credential, its apps' headers and env
2. write the agent's files and skills, configure its MCP servers, pick the engine:
     anthropic -> Claude Code (`claude -p`), api key or `setup-token` subscription
     openai    -> Codex (`codex exec`), api key or ChatGPT auth.json
3. loop: GET /api/runtime/inbox for the owner's messages; for each one run a turn of the CLI,
   resuming the same conversation, and POST /api/runtime/events with what the agent says and does.
   Before each turn, GET /api/runtime/secrets: an app's sign-in may have been refreshed since.
   Polling the inbox is the heartbeat between turns; during one, GET /api/runtime/ping is
4. after each turn, if the agent changed its notes, PUT /api/runtime/memory so its next chat has them;
   between turns, pick up the owner's edits to them (the inbox says when they changed)
5. exit when the owner has been quiet for AGENTTOWN_IDLE_MINUTES, or the API says the run ended

Each turn is a fresh CLI process that resumes the conversation by id: simple, and a crash in
one turn can't wedge the next.

A manifest of kind "caretaker" is Agent Town's own helper (backend/app/caretaker.py), not an agent:
its instructions replace Claude Code's own, and it gets no file tools, only its MCP tools.
"""

import hashlib
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ["AGENTTOWN_API_URL"].rstrip("/")
TOKEN = os.environ["AGENTTOWN_RUN_TOKEN"]
ALLOW_SHELL = os.environ.get("AGENTTOWN_ALLOW_SHELL") == "1"
IDLE = int(os.environ.get("AGENTTOWN_IDLE_MINUTES", "15")) * 60
ROOT = Path.cwd()
WORK = ROOT / "work"          # the agent's working directory: its files, and public/ items
HOME = Path(os.environ.get("HOME", ROOT / "home"))
CLIP = 4000                   # how much of a tool's output goes back to the UI
# What it remembers. Agent file paths can't start with ".", so nothing it was given can clash with these.
MEMORY, RECENT = ".agent-town/memory.md", ".agent-town/recent-chats.md"
ABOUT_ME = "about-me.md"      # what its owner told it alone; it may write this one, and it's kept (AboutMe)


class Ended(Exception):
    pass


RETRIES = 4                   # a tunnel hiccup or a deploy mustn't end a run: try again, briefly
HEARTBEAT = 20                # seconds between pings while a turn runs (the API gives up after minutes)


def api(method: str, path: str, body: dict | None = None) -> dict:
    """One call to Agent Town. Network trouble and 5xx are retried with a short backoff; a 401 means
    the run ended (the owner stopped it, or it was reaped) and any other 4xx is the caller's."""
    data = json.dumps(body).encode() if body else None
    for attempt in range(RETRIES + 1):
        req = urllib.request.Request(API + path, method=method, data=data,
                                     headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise Ended("the run ended") from e
            if e.code < 500 or attempt == RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == RETRIES:
                raise
        time.sleep(min(2 ** attempt, 10))
    raise RuntimeError("unreachable")


def emit(kind: str, **data) -> None:
    api("POST", "/api/runtime/events", {"events": [{"kind": kind, "data": data}]})


def clip(v) -> str:
    s = v if isinstance(v, str) else json.dumps(v)
    return s if len(s) <= CLIP else s[:CLIP] + f"… ({len(s) - CLIP} more characters)"


def server_name(name: str) -> str:
    """Lowercase, like the names people give MCP servers in Claude Code: "Gmail" -> mcp__gmail__…"""
    return re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_") or "server"


def safe_rel(rel: str) -> str | None:
    """A path we'll write under a folder, or None. The API validates paths, but the sandbox is the
    last line: nothing absolute, hidden or climbing out ("..") gets written."""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if rel.startswith("/") or any(s in ("", "..") or s.startswith(".") for s in parts):
        return None
    return posixpath.normpath(rel)


def write_under(base: Path, rel: str, content: str) -> bool:
    """Write base/rel, if rel stays inside base. Returns whether it was written."""
    rel = safe_rel(rel)
    if rel is None:
        return False
    dest = (base / rel).resolve()
    if base.resolve() not in dest.parents:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    return True


# At the root of a shared item these names would be read as project memory (Claude Code: CLAUDE.md,
# Codex: AGENTS.md) or as skills/sub-agents. Someone else's share must stay a file, not instructions.
PUBLIC_RENAME = {"CLAUDE.md": "CLAUDE.shared.md", "AGENTS.md": "AGENTS.shared.md"}
PUBLIC_SKIP = ("skills/", ".claude/")


def public_path(path: str) -> str | None:
    rel = safe_rel(path)
    if rel is None or rel.startswith(PUBLIC_SKIP):
        return None
    return PUBLIC_RENAME.get(rel, rel)


def write_files(m: dict) -> list[str]:
    """Public items first (each confined to its own public/<owner>/<title>/ folder), then shared
    files, then the agent's own, which win on a clash. Returns the paths written, so the agent can
    be told what it has."""
    WORK.mkdir(parents=True, exist_ok=True)
    written = []
    for p in m.get("public", []):
        base = WORK / "public" / server_name(str(p.get("owner", ""))) / server_name(p["title"])
        files = [p["file"]] if p.get("file") else (p.get("agent") or {}).get("files", [])
        for f in files:
            rel = public_path(f["path"])
            if rel and write_under(base, rel, f.get("content", "")):
                written.append(base.relative_to(WORK).as_posix() + "/" + rel)
    own = [(f["path"], f["content"]) for f in m.get("shared", [])]
    own += [(f["path"], f["content"]) for f in m["files"] if f["path"] != "AGENT.md"]
    for rel, content in own:
        safe = safe_rel(rel)
        if safe and write_under(WORK, safe, content) and safe not in written:
            written.append(safe)
    return written


def write_team(m: dict) -> list[dict]:
    """Each teammate's files go under team/<slug>/, so they never mix with the lead's."""
    out = []
    for t in m.get("team", []):
        base = WORK / "team" / server_name(t["slug"])
        paths = []
        for f in t["files"]:
            rel = safe_rel(f["path"])
            if rel and write_under(base, rel, f["content"]):
                paths.append(f"team/{base.name}/{rel}")
        out.append({**t, "paths": paths})
    return out


def write_recent(m: dict) -> None:
    """Its last few chats, words only, newest first."""
    chats = m.get("recent_chats") or []
    if not chats:
        return
    out = ["# Your recent chats", "", "Newest first: what was said, not what you did. Read-only; keep anything"
           f" worth remembering in {MEMORY}.", ""]
    for c in chats:
        out += [f"## {c['started_at'][:16].replace('T', ' ')} UTC", ""]
        if c.get("cut"):
            out += ["(earlier messages in this chat left out)", ""]
        out += [f"**{ {'owner': 'They', 'mail': 'Mail'}.get(x['who'], 'You') }:** {x['text']}\n" for x in c["messages"]]
    (WORK / RECENT).parent.mkdir(parents=True, exist_ok=True)
    (WORK / RECENT).write_text("\n".join(out))


def tag(text: str) -> str:
    """The same fingerprint the API uses (routers/runs.py memory_tag)."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


class Memory:
    """Its notes file, kept in step with the server. The owner may edit the notes mid-chat (the
    Diary): between turns that edit is copied in, and a save that started from older notes is
    refused, so the owner's version always wins and the agent is told to look again."""

    def __init__(self, notes: str):
        self.file = WORK / MEMORY
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.note = ""                  # said to the agent with the next message, then cleared
        self._take(notes)

    def _take(self, notes: str) -> None:
        self.saved = notes
        self.file.write_text(notes)

    def _reload(self, why: str) -> None:
        self._take(api("GET", "/api/runtime/memory")["content"])
        self.note = why

    def check(self, server_tag: str | None) -> None:
        """Between turns: did the owner change the notes?"""
        if server_tag and server_tag != tag(self.saved):
            self._reload(f"(The person you work for edited {MEMORY} since you last read it. Read it again before relying on it.)")

    def save(self) -> None:
        """After a turn: send the notes back if the agent changed them."""
        try:
            notes = self.file.read_text()
        except (OSError, UnicodeDecodeError):
            return              # deleted or garbled: keep what was saved rather than wipe it
        if notes == self.saved:
            return
        try:
            api("PUT", "/api/runtime/memory", {"content": notes, "base": tag(self.saved)})
        except urllib.error.HTTPError as e:
            if e.code == 409:
                self._reload(f"(The person you work for edited {MEMORY} while you were working, so the changes you"
                             " made to it weren't kept. Read it again and redo any that still matter.)")
                return
            if e.code != 422:
                raise
            emit("error", detail=f"{MEMORY} is over 20,000 characters, so this version wasn't kept. Ask it to shorten its notes.")
            return
        self.saved = notes

    def tell(self, text: str) -> str:
        """The owner's message, with anything the agent should know about its notes first."""
        note, self.note = self.note, ""
        return f"{note}\n\n{text}" if note else text


class AboutMe:
    """about-me.md: what its owner told it alone. The agent may write it (its first chat interviews
    them), so after each turn a changed file is sent back and kept for the next chat."""

    def __init__(self):
        self.file = WORK / ABOUT_ME
        self.saved = self._read()

    def _read(self) -> str:
        try:
            return self.file.read_text()
        except (OSError, UnicodeDecodeError):
            return ""

    def save(self) -> None:
        text = self._read()
        if text == self.saved or not text.strip():
            return              # unchanged, or deleted: keep what was saved rather than wipe it
        try:
            api("PUT", "/api/runtime/about-me", {"content": text})
        except urllib.error.HTTPError as e:
            if e.code != 422:
                raise
            emit("error", detail=f"{ABOUT_ME} is too long to keep, so this version wasn't saved.")
            return
        self.saved = text


def system_prompt(m: dict, files: list[str]) -> str:
    """The agent's own instructions, plus where its files are. Instructions written for another
    setup may link `../../content/a.md`; the list lets it find content/a.md here."""
    extra = "\n\n---\nYour files are in the current directory."
    if "about-us.md" in files:
        extra += (" about-us.md is what the person you work for told all their agents about themselves and their"
                  " company: read it first and use it.")
    if "about-me.md" in files:
        extra += (" about-me.md is what they told you alone, for your job: read it too." if "about-us.md" in files else
                  " about-me.md is what the person you work for told you about themselves: read it first and use it.")
    if files:
        shown = files[:200]
        extra += " Read the ones your instructions mention before you start:\n" + "\n".join(f"- {f}" for f in shown)
        if len(files) > len(shown):
            extra += f"\n- … and {len(files) - len(shown)} more"
    if m["public"]:
        extra += "\nThings other people shared for agents to read are under public/<owner>/."
    if m.get("team"):
        extra += ("\n\nYour team (hand work to them with the Task tool; each has its own files and tools):\n"
                  + "\n".join(f"- {t['slug']}: {t['description'] or t['name']}" for t in m["team"]))
    extra += (f"\n\nYou don't remember past chats on your own, so you have two files for it. Read both before you"
              f" start.\n- {MEMORY}: your notes, kept between chats (only this file is kept). When you learn"
              " something worth knowing next time (their preferences, decisions made, work still open, what to"
              " follow up on), update it before you answer. Keep it short and current: rewrite it rather than"
              " append, under 20,000 characters, and never put passwords or keys in it.")
    if m.get("recent_chats"):
        extra += f"\n- {RECENT}: what was said in your last few chats, newest first."
    if m.get("interview"):
        extra += interview_prompt(m["interview"], "about-us.md" in files)
    return m["instructions"] + extra


def interview_prompt(questions: list[str], has_profile: bool) -> str:
    """Its first chat: get to know the person, in conversation. The questions are the ones its
    definition asks (`ask:`); the answers go to about-me.md, which is kept and read in every chat."""
    return ("\n\nYou've just been added and don't know the person you work for yet. These are the things you"
            " want to learn, for your job:\n" + "\n".join(f"- {q}" for q in questions) +
            "\n\nIn this chat, get to know them, like a new colleague on their first day, not a form:"
            + ("\n- Read about-us.md first. Don't ask what it already answers; say what you took from it instead."
               if has_profile else "") +
            "\n- Start by saying in a sentence or two what you'll do for them, then ask one or two questions at"
            " a time, in your own words. Follow up when an answer is vague; move on when they skip one."
            "\n- When you could find an answer yourself with the apps you have (their sent emails for their voice,"
            " their calendar for when they meet), offer to look instead of asking them to type or paste it, and"
            " look only once they say yes."
            "\n- If they ask you for something straight away, do that first, and ask only what you need for it."
            "\n- Keep it short: a few minutes, not an interview with twenty questions."
            f"\n- As you learn things, write them to {ABOUT_ME} (create it): short notes under a heading per topic,"
            " in their words where it matters. It's kept, they can read and edit it, and you read it in every"
            " chat. Don't put passwords or keys in it."
            "\n- When you're done, tell them in a line what you'll remember and that they can change it any time"
            f" in {ABOUT_ME} in your house, then ask what they'd like to start with.")


def servers(m: dict, secrets: dict, tools: list[dict] | None = None) -> list[dict]:
    """The MCP servers this agent was granted, and which of their tools (None: all of them)."""
    out = []
    for t in m["tools"] if tools is None else tools:
        if not t["usable"]:
            continue
        # hosted (Gmail, Calendar, web APIs): Agent Town serves those tools itself; this run's token gets in
        own = {"headers": {"Authorization": f"Bearer {TOKEN}"}, "env": {}} if t.get("hosted") \
            else secrets.get(str(t["connection_id"])) or {"headers": {}, "env": {}}
        out.append({"name": server_name(t.get("server") or t["connection"]), "transport": t["transport"], "url": t["url"],
                    "command": t["command"], "headers": own["headers"], "env": own["env"],
                    "tools": None if t["all_tools"] else [x["name"] for x in t["tools"]]})
    return out


def fresh_secrets() -> dict:
    return api("GET", "/api/runtime/secrets").get("secrets") or {}


def install_skills(dest: Path) -> list[str]:
    """Skills (skills/<name>/SKILL.md, from its own or the owner's shared files) go where the CLI
    looks for them, so it loads each one when a task calls for it, as Claude Code and Codex do."""
    names = []
    for skill in sorted((WORK / "skills").glob("*/SKILL.md")):
        target = dest / skill.parent.name
        target.mkdir(parents=True, exist_ok=True)
        for f in skill.parent.rglob("*"):
            if f.is_file():
                (target / f.relative_to(skill.parent)).parent.mkdir(parents=True, exist_ok=True)
                (target / f.relative_to(skill.parent)).write_text(f.read_text())
        names.append(skill.parent.name)
    return names


class Heartbeat:
    """Pings the API while a turn runs. Between turns the inbox poll is the heartbeat; during one the
    runner is busy reading the CLI, and a long tool call would otherwise look like a dead box."""

    def __init__(self):
        self.stop = threading.Event()

    def __enter__(self):
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def __exit__(self, *_):
        self.stop.set()

    def _loop(self):
        while not self.stop.wait(HEARTBEAT):
            try:
                api("GET", "/api/runtime/ping")
            except Ended:
                return
            except Exception as e:  # noqa: BLE001  (the next ping, or the turn's own calls, will say)
                print(f"ping failed: {type(e).__name__}: {e}", file=sys.stderr)


def drain(pipe, keep: int = 2000) -> list[str]:
    """Read a pipe to the end on a thread, keeping its tail. The CLI's stderr can be chatty (MCP
    servers, reconnect logs); unread, it fills the pipe and the CLI blocks, and the turn hangs."""
    tail = [""]

    def read():
        for chunk in pipe:
            tail[0] = (tail[0] + chunk)[-keep:]
    threading.Thread(target=read, daemon=True).start()
    return tail


def parse_lines(lines, on_line) -> None:
    """Hand each JSON line to on_line; anything else the CLI prints is skipped."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        on_line(msg)


def stream(cmd: list[str], prompt: str, env: dict, on_line) -> tuple[int, str]:
    """Run one turn of a CLI, handing each JSON line of its output to on_line as it arrives."""
    p = subprocess.Popen(cmd, cwd=WORK, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    p.stdin.write(prompt)
    p.stdin.close()
    err = drain(p.stderr)
    with Heartbeat():
        parse_lines(p.stdout, on_line)
    code = p.wait()
    time.sleep(0.05)             # let the stderr reader catch the last lines
    return code, err[0]


class Claude:
    """Claude Code in print mode. Tools: file tools in the working directory (plus Bash in a real
    sandbox) and exactly the granted MCP tools. dontAsk mode refuses anything not allowed."""

    def __init__(self, m: dict, cred: dict, secrets: dict, files: list[str], team: list[dict] | None = None):
        self.model, self.effort = cred["model"], cred.get("thinking") or ""
        self.caretaker = m.get("kind") == "caretaker"
        self.session, self.system = None, m["instructions"] if self.caretaker else system_prompt(m, files)
        self.m, self.team = m, team or []
        self.env = {**os.environ}
        for k in ("AGENTTOWN_RUN_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
            self.env.pop(k, None)
        self.env["ANTHROPIC_API_KEY" if cred["kind"] == "api_key" else "CLAUDE_CODE_OAUTH_TOKEN"] = cred["secret"]
        builtin = [] if self.caretaker else ["Read", "Write", "Edit", "Glob", "Grep"] + (["Bash"] if ALLOW_SHELL else [])
        if not self.caretaker and install_skills(WORK / ".claude" / "skills"):
            builtin.append("Skill")
        self.tools, allowed = list(builtin), list(builtin)

        def names(srv: list[dict]) -> list[str]:
            return [n for s in srv for n in ([f"mcp__{s['name']}"] if s["tools"] is None
                                             else [f"mcp__{s['name']}__{t}" for t in s["tools"] if "," not in t])]

        allowed += names(servers(m, secrets))
        if self.team:                              # teammates become Claude Code sub-agents in .claude/agents/
            self.tools.append("Task")
            allowed.append("Task")
            agents_dir = WORK / ".claude" / "agents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            for t in self.team:
                own = names(servers(m, secrets, t["tools"]))
                allowed += own
                desc = (t["description"] or t["name"]).replace("\n", " ")
                body = t["instructions"] + ("\n\nYour files are in team/" + t["slug"] + "/:\n" + "\n".join(f"- {p}" for p in t["paths"]) if t["paths"] else "")
                (agents_dir / f"{t['slug']}.md").write_text(
                    f"---\nname: {t['slug']}\ndescription: {json.dumps(desc)}\ntools: {', '.join(builtin + own)}\n---\n\n{body}\n")
        self.allowed = list(dict.fromkeys(allowed))
        self.mcp = HOME / "mcp.json"
        self.write_mcp(secrets)

    def write_mcp(self, secrets: dict) -> None:
        """Claude Code's --mcp-config: the lead's servers and its teammates'."""
        config = {}
        for s in servers(self.m, secrets) + [x for t in self.team for x in servers(self.m, secrets, t["tools"])]:
            if s["transport"] == "http":
                config[s["name"]] = {"type": "http", "url": s["url"], **({"headers": s["headers"]} if s["headers"] else {})}
            else:
                argv = shlex.split(s["command"] or "")
                config[s["name"]] = {"type": "stdio", "command": argv[0], "args": argv[1:], **({"env": s["env"]} if s["env"] else {})}
        self.mcp.write_text(json.dumps({"mcpServers": config}))
        self.mcp.chmod(0o600)

    def turn(self, text: str) -> None:
        self.write_mcp(fresh_secrets())
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose", "--permission-mode", "dontAsk",
               f"--tools={','.join(self.tools)}", f"--allowedTools={','.join(self.allowed)}",
               "--strict-mcp-config", "--mcp-config", str(self.mcp),
               "--system-prompt" if self.caretaker else "--append-system-prompt", self.system]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        if self.session:
            cmd += ["--resume", self.session]
        finished = False

        def on_line(msg: dict) -> None:
            nonlocal finished
            t = msg.get("type")
            if msg.get("session_id"):
                self.session = msg["session_id"]
            if t == "assistant" and (msg.get("message") or {}).get("model") != "<synthetic>":  # synthetic: an error, reported below
                for b in (msg.get("message") or {}).get("content") or []:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        emit("text", text=b["text"])
                    elif b.get("type") == "tool_use":
                        emit("tool", name=b.get("name", ""), input=clip(b.get("input")))
            elif t == "user":
                for b in (msg.get("message") or {}).get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        c = b.get("content")
                        if isinstance(c, list):
                            c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
                        emit("tool_result", output=clip(c or ""), is_error=bool(b.get("is_error")))
            elif t == "result":
                finished = True
                ok = not msg.get("is_error")
                if not ok:
                    emit("error", detail=clip(msg.get("result") or msg.get("subtype") or "The turn failed"))
                emit("done", ok=ok, cost_usd=msg.get("total_cost_usd"), duration_ms=msg.get("duration_ms"),
                     turns=msg.get("num_turns"), auth_failed=msg.get("api_error_status") in (401, 403))

        code, err = stream(cmd, text, self.env, on_line)
        if not finished:
            emit("error", detail=f"claude exited with {code}: {err or 'no output'}")
            emit("done", ok=False)


def toml_str(s: str) -> str:
    return json.dumps(s)  # a JSON string is a valid TOML basic string


class Codex:
    """Codex in exec mode, configured through its own CODEX_HOME so nothing else is read."""

    def __init__(self, m: dict, cred: dict, secrets: dict, files: list[str]):
        self.model, self.thread, self.m = cred["model"], None, m
        self.home = HOME / ".codex"
        self.home.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, "CODEX_HOME": str(self.home)}
        for k in ("AGENTTOWN_RUN_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY"):
            self.env.pop(k, None)
        if cred["kind"] == "api_key":
            self.env["CODEX_API_KEY"] = cred["secret"]
        else:
            (self.home / "auth.json").write_text(cred["secret"])
            (self.home / "auth.json").chmod(0o600)
        install_skills(self.home / "skills")
        self.write_config(secrets)
        # In a real sandbox the container is the boundary; locally, Codex's own sandbox is.
        mode = "danger-full-access" if ALLOW_SHELL else "workspace-write"
        self.common = ["--json", "--skip-git-repo-check", "-c", f"sandbox_mode={toml_str(mode)}",
                       "-c", 'approval_policy="never"', "-c", f"developer_instructions={toml_str(system_prompt(m, files))}"]
        if self.model:
            self.common += ["-m", self.model]
        effort = {"max": "xhigh"}.get(cred.get("thinking") or "", cred.get("thinking") or "")
        if effort:
            self.common += ["-c", f"model_reasoning_effort={toml_str(effort)}"]

    def write_config(self, secrets: dict) -> None:
        """Codex reads its MCP servers from config.toml in CODEX_HOME."""
        def table(d: dict) -> str:
            return "{ " + ", ".join(f"{toml_str(k)} = {toml_str(v)}" for k, v in d.items()) + " }"
        lines = []
        for s in servers(self.m, secrets):
            lines.append(f"[mcp_servers.{s['name']}]")
            if s["transport"] == "http":
                lines.append(f"url = {toml_str(s['url'])}")
                if s["headers"]:
                    lines.append(f"http_headers = {table(s['headers'])}")
            else:
                argv = shlex.split(s["command"] or "")
                lines.append(f"command = {toml_str(argv[0])}")
                lines.append(f"args = [{', '.join(toml_str(a) for a in argv[1:])}]")
                if s["env"]:
                    lines.append(f"env = {table(s['env'])}")
            if s["tools"] is not None:
                lines.append(f"enabled_tools = [{', '.join(toml_str(t) for t in s['tools'])}]")
        (self.home / "config.toml").write_text("\n".join(lines) + "\n")
        (self.home / "config.toml").chmod(0o600)

    def turn(self, text: str) -> None:
        self.write_config(fresh_secrets())
        cmd = ["codex", "exec", "resume", self.thread, *self.common, "-"] if self.thread else \
              ["codex", "exec", *self.common, "-"]
        finished = False

        def on_line(msg: dict) -> None:
            nonlocal finished
            t = msg.get("type")
            if t == "thread.started":
                self.thread = msg.get("thread_id") or self.thread
            elif t == "item.started":
                it = msg.get("item") or {}
                if it.get("type") == "mcp_tool_call":
                    emit("tool", name=f"{it.get('server')}.{it.get('tool')}", input=clip(it.get("arguments")))
                elif it.get("type") == "command_execution":
                    emit("tool", name="shell", input=clip(it.get("command", "")))
            elif t == "item.completed":
                it = msg.get("item") or {}
                kind = it.get("type")
                if kind == "agent_message" and it.get("text", "").strip():
                    emit("text", text=it["text"])
                elif kind == "mcp_tool_call":
                    emit("tool_result", output=clip(it.get("result") or it.get("error") or ""),
                         is_error=it.get("status") == "failed")
                elif kind == "command_execution":
                    emit("tool_result", output=clip(it.get("aggregated_output", "")), is_error=it.get("exit_code") not in (0, None))
                elif kind == "file_change":
                    emit("tool", name="edit", input=clip(it.get("changes")))
            elif t == "turn.completed":
                finished = True
                emit("done", ok=True, usage=msg.get("usage"))
            elif t == "turn.failed":  # plain "error" events are retries ("Reconnecting... 2/5"); this one is final
                finished = True
                detail = (msg.get("error") or {}).get("message") or "The turn failed"
                emit("error", detail=clip(detail))
                emit("done", ok=False, auth_failed="401 Unauthorized" in detail)

        code, err = stream(cmd, text, self.env, on_line)
        if not finished:
            emit("error", detail=f"codex exited with {code}: {err or 'no output'}")
            emit("done", ok=False)


def main() -> None:
    setup = api("GET", "/api/runtime/setup")
    m, cred = setup["manifest"], setup["credential"]
    HOME.mkdir(parents=True, exist_ok=True)
    files = write_files(m)
    team = write_team(m)
    write_recent(m)
    memory = Memory(m.get("memory") or "")
    about = AboutMe()
    if cred["provider"] == "anthropic":
        engine = Claude(m, cred, setup["secrets"], files, team)
    else:
        engine = Codex({**m, "team": []}, cred, setup["secrets"], files)
        if team:
            emit("error", detail="Teams need a Claude model for now: this agent runs on Codex, so it works alone.")
    emit("status", status="ready", detail=f"{m['agent']['name']} is ready")
    cursor, last_turn = 0, time.monotonic()
    while True:
        box = api("GET", f"/api/runtime/inbox?after={cursor}")
        memory.check(box.get("memory"))
        for msg in box["messages"]:
            cursor = msg["id"]
            emit("status", status="busy")
            try:
                engine.turn(memory.tell(msg["text"]))
            except Ended:
                raise
            except Exception as e:  # noqa: BLE001  (one bad turn shouldn't end the run)
                emit("error", detail=f"{type(e).__name__}: {e}")
                emit("done", ok=False)
            memory.save()
            about.save()
            emit("status", status="ready")
            last_turn = time.monotonic()
        if not box["messages"]:
            # quiet since the owner's last message, and since the agent's last answer
            if box["idle_seconds"] > IDLE and time.monotonic() - last_turn > IDLE:
                emit("status", status="stopped", detail="Stopped after being idle")
                return
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except Ended:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"runner failed: {type(e).__name__}: {e}", file=sys.stderr)
        try:
            emit("status", status="error", detail=f"runner: {type(e).__name__}: {e}")
        except Exception as x:  # noqa: BLE001  (nothing more to do; the provider's log keeps this)
            print(f"and couldn't tell Agent Town: {type(x).__name__}: {x}", file=sys.stderr)
        sys.exit(1)
