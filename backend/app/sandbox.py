"""Where a run's sandbox comes from. A provider only starts and stops a box that runs
runner/runner.py; everything else (what the agent gets, its credentials, the conversation) goes
over the runtime API with the run token, so every provider behaves the same.

  local  a subprocess on this machine, in a temp directory with a clean environment.
         Development only: it is NOT isolated from your computer, so the agent gets no shell.
  modal  a Modal Sandbox (a gVisor container) per run, from an image with Node, uv, Claude Code and
         Codex baked in. Modal builds the image once and caches it, so later runs start fast.
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import settings

RUNNER = Path(__file__).resolve().parent.parent / "runner" / "runner.py"


def runner_env(run_id: int, token: str, allow_shell: bool) -> dict[str, str]:
    """All a sandbox is told at start. Credentials come later, over the API, with the token."""
    return {"AGENTTOWN_API_URL": settings().public_url.rstrip("/"), "AGENTTOWN_RUN_TOKEN": token,
            "AGENTTOWN_RUN_ID": str(run_id), "AGENTTOWN_ALLOW_SHELL": "1" if allow_shell else "0",
            "AGENTTOWN_IDLE_MINUTES": str(settings().run_idle_minutes)}


class LocalProvider:
    name = "local"
    _procs: dict[int, subprocess.Popen] = {}
    _started: dict[int, float] = {}       # pid -> when (monotonic): the local box has no timeout of its own

    def start(self, run_id: int, token: str) -> str:
        root = Path(tempfile.mkdtemp(prefix=f"agenttown-run{run_id}-"))
        (root / "home").mkdir()
        # A clean environment: none of *your* keys or logins leak into the agent's tools.
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(root / "home"), "LANG": "C.UTF-8",
               **runner_env(run_id, token, allow_shell=False)}
        with open(root / "runner.log", "ab") as log:   # the child keeps its own copy of the descriptor
            p = subprocess.Popen([sys.executable, str(RUNNER)], cwd=root, env=env, stdout=log, stderr=log,
                                 start_new_session=True)  # its own process group, so stop() gets the CLIs too
        self._procs[p.pid], self._started[p.pid] = p, time.monotonic()
        return f"{p.pid}:{root}"

    def alive(self, sandbox_id: str) -> bool:
        pid_s = sandbox_id.partition(":")[0]
        p = self._procs.get(int(pid_s)) if pid_s.isdigit() else None
        if p is None or p.poll() is not None:
            return False
        if time.monotonic() - self._started.get(p.pid, 0) > settings().run_max_hours * 3600:
            self.stop(sandbox_id)              # Modal has a hard timeout; this is the local one
            return False
        return True

    def stop(self, sandbox_id: str) -> None:
        pid_s, _, root = sandbox_id.partition(":")
        try:
            os.killpg(int(pid_s), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
        p = self._procs.pop(int(pid_s), None) if pid_s.isdigit() else None
        if pid_s.isdigit():
            self._started.pop(int(pid_s), None)
        if p:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        if root.startswith(tempfile.gettempdir()):
            shutil.rmtree(root, ignore_errors=True)


class ModalProvider:
    name = "modal"
    APP = "agent-town"

    def _image(self):
        import modal
        return (modal.Image.debian_slim(python_version="3.12")
                .apt_install("curl", "ca-certificates", "git")
                .run_commands("curl -fsSL https://deb.nodesource.com/setup_22.x | bash -",
                              "apt-get install -y nodejs",
                              "npm install -g @anthropic-ai/claude-code @openai/codex")
                .pip_install("uv")    # uvx: Python MCP servers, as npx is for Node ones
                .add_local_file(str(RUNNER), "/agent/runner.py"))

    def start(self, run_id: int, token: str) -> str:
        import modal
        app = modal.App.lookup(self.APP, create_if_missing=True)
        sb = modal.Sandbox.create(
            "python", "/agent/runner.py", app=app, image=self._image(), workdir="/agent",
            secrets=[modal.Secret.from_dict({**runner_env(run_id, token, allow_shell=True), "IS_SANDBOX": "1"})],
            timeout=settings().run_max_hours * 3600)  # a hard stop, even if the runner hangs
        return sb.object_id

    def alive(self, sandbox_id: str) -> bool:
        import modal
        return modal.Sandbox.from_id(sandbox_id).poll() is None

    def stop(self, sandbox_id: str) -> None:
        import modal
        modal.Sandbox.from_id(sandbox_id).terminate()


def provider(name: str | None = None):
    name = name or settings().sandbox_provider
    if name == "local":
        return LocalProvider()
    if name == "modal":
        return ModalProvider()
    raise ValueError(f"Unknown sandbox provider {name!r} (local | modal)")
