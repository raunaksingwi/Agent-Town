"""Password guessing is slowed down, and a password change signs other browsers out."""

from fastapi.testclient import TestClient

from app import ratelimit
from app.main import app


def test_login_is_rate_limited(make_user, monkeypatch):
    make_user("alice")
    monkeypatch.setattr(ratelimit, "enabled", True)
    ratelimit.reset()
    c = TestClient(app)
    for _ in range(10):
        assert c.post("/api/auth/login", json={"login": "alice", "password": "wrong"}).status_code == 401
    r = c.post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"})
    assert r.status_code == 429 and "wait" in r.json()["detail"]
    # another account from the same address still works (the per-address cap is wider)
    make_user("bob")
    assert c.post("/api/auth/login", json={"login": "bob", "password": "correct horse battery"}).status_code == 200


def test_signup_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "enabled", True)
    ratelimit.reset()
    for i in range(10):
        r = client.post("/api/auth/signup", json={"email": f"u{i}@example.com", "username": f"user{i}", "password": "correct horse battery"})
        assert r.status_code == 200
    r = client.post("/api/auth/signup", json={"email": "u11@example.com", "username": "user11", "password": "correct horse battery"})
    assert r.status_code == 429


def test_forwarded_address_counts_only_behind_a_proxy(client, monkeypatch):
    monkeypatch.setattr(ratelimit, "enabled", True)
    ratelimit.reset()
    for i in range(10):
        client.post("/api/auth/signup", json={"email": f"v{i}@example.com", "username": f"vuser{i}", "password": "correct horse battery"})
    # forging X-Forwarded-For without a proxy doesn't get a fresh allowance
    r = client.post("/api/auth/signup", json={"email": "v11@example.com", "username": "vuser11", "password": "correct horse battery"},
                    headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 429
    r = client.post("/api/auth/signup", json={"email": "v11@example.com", "username": "vuser11", "password": "correct horse battery"},
                    headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"})
    assert r.status_code == 200


def test_password_change_signs_out_other_browsers(make_user):
    alice = make_user("alice")
    other = TestClient(app)
    assert other.post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"}).status_code == 200
    assert other.get("/api/auth/me").json()["username"] == "alice"
    r = alice.post("/api/account/password", json={"password": "wrong", "new_password": "a brand new one"})
    assert r.status_code == 403
    r = alice.post("/api/account/password", json={"password": "correct horse battery", "new_password": "a brand new one"})
    assert r.status_code == 200 and r.json()["signed_out"] == 1
    assert other.get("/api/auth/me").json() is None                       # signed out
    assert alice.get("/api/auth/me").json()["username"] == "alice"         # this browser stays
    assert TestClient(app).post("/api/auth/login", json={"login": "alice", "password": "a brand new one"}).status_code == 200
    assert TestClient(app).post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"}).status_code == 401


def test_sign_out_others(make_user):
    alice = make_user("alice")
    other = TestClient(app)
    other.post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"})
    assert alice.post("/api/account/sessions/sign-out-others").json()["signed_out"] == 1
    assert other.get("/api/auth/me").json() is None
