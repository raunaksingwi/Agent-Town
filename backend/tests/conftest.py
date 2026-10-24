import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import sandbox
from app.db import Base, get_db, make_engine
from app.main import app


@pytest.fixture(autouse=True)
def test_settings(monkeypatch):
    """Tests must not depend on a developer's backend/.env (which may say modal, or a tunnel URL)."""
    from app import ratelimit
    from app.config import settings
    ratelimit.reset()
    monkeypatch.setattr(ratelimit, "enabled", False)
    for k, v in {"sandbox_provider": "local", "public_url": "http://127.0.0.1:8000", "app_url": "http://127.0.0.1:8000",
                 "allow_subscription_tokens": True, "allow_private_mcp_hosts": False, "scheduler": False,
                 "google_client_id": "", "google_client_secret": ""}.items():
        monkeypatch.setattr(settings(), k, v)
    # module state that would otherwise carry over between tests (run ids start at 1 in every test database)
    from app import runs
    runs._checked.clear()
    monkeypatch.setattr(runs, "_reachable_until", 0.0)


class FakeProvider:
    """Stands in for a sandbox provider: remembers what it was asked to start and stop."""
    name = "fake"
    started: list[tuple[int, str]] = []     # (run id, run token)
    stopped: list[str] = []
    dead: set = set()

    def start(self, run_id, token):
        self.started.append((run_id, token))
        return f"fake-{run_id}"

    def stop(self, sandbox_id):
        self.stopped.append(sandbox_id)

    def alive(self, sandbox_id):
        return sandbox_id not in self.dead


@pytest.fixture
def fake_sandbox(monkeypatch):
    FakeProvider.started, FakeProvider.stopped, FakeProvider.dead = [], [], set()
    monkeypatch.setattr(sandbox, "provider", lambda name=None: FakeProvider())
    return FakeProvider


def box(client: TestClient, token: str) -> TestClient:
    """A client that talks like the sandbox: only the run token, no cookie."""
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def load_runner(tmp_path, monkeypatch):
    """The sandbox runner as a module, pointed at a scratch WORK and HOME, with the API stubbed out."""
    monkeypatch.setenv("AGENTTOWN_API_URL", "http://x")
    monkeypatch.setenv("AGENTTOWN_RUN_TOKEN", "rt_x")
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "runner"))
    sys.modules.pop("runner", None)
    runner = importlib.import_module("runner")
    monkeypatch.setattr(runner, "HOME", tmp_path / "home")
    monkeypatch.setattr(runner, "WORK", tmp_path / "work")
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "work").mkdir(exist_ok=True)
    monkeypatch.setattr(runner, "fresh_secrets", lambda: {})
    return runner


@pytest.fixture
def db_session(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    from app import push
    push._session, push._send_sync = Session, True       # notifications: this database, in the test's own thread
    push._watched.clear()
    yield Session
    push._session, push._send_sync = None, False
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_session):
    return TestClient(app)


@pytest.fixture
def make_user(db_session):
    """A fresh signed-in client per user, so cookies don't mix."""
    def make(username: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/api/auth/signup", json={"email": f"{username}@example.com", "username": username,
                                             "password": "correct horse battery"})
        assert r.status_code == 200, r.text
        return c
    return make


AGENT_MD = """---
name: reel-writer
description: Scripts short videos.
---

# Reel writer

Write hooks and shot lists.
"""
