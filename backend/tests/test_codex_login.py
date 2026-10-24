"""Sign in with ChatGPT: the device-code login, with OpenAI faked by httpx.MockTransport."""

import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app import codex_login
from app.config import settings
from app.models import ModelCredential
from app.security import decrypt


def jwt(claims: dict) -> str:
    b = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"h.{b}.s"


ID_TOKEN = jwt({"email": "alice@example.com", "https://api.openai.com/auth": {"chatgpt_account_id": "acct-1"}})


class FakeOpenAI:
    def __init__(self):
        self.approved, self.exchanged = False, []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/accounts/deviceauth/usercode":
            assert json.loads(req.content) == {"client_id": codex_login.CLIENT_ID}
            return httpx.Response(200, json={"device_auth_id": "dev-secret", "user_code": "ABCD-1234", "interval": "5"})
        if path == "/api/accounts/deviceauth/token":
            assert json.loads(req.content) == {"device_auth_id": "dev-secret", "user_code": "ABCD-1234"}
            if not self.approved:
                return httpx.Response(403, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"authorization_code": "auth-code", "code_challenge": "ch", "code_verifier": "ver"})
        if path == "/oauth/token":
            self.exchanged.append(parse_qs(req.content.decode()))
            return httpx.Response(200, json={"id_token": ID_TOKEN, "access_token": "at-1", "refresh_token": "rt-1"})
        return httpx.Response(404)


@pytest.fixture
def openai(monkeypatch):
    fake = FakeOpenAI()
    monkeypatch.setattr(codex_login, "http", lambda: httpx.Client(transport=httpx.MockTransport(fake)))
    return fake


def test_sign_in_with_chatgpt_saves_codex_auth_json(make_user, openai, db_session):
    alice = make_user("alice")
    s = alice.post("/api/account/credentials/chatgpt/start").json()
    assert s["code"] == "ABCD-1234" and s["url"] == "https://auth.openai.com/codex/device" and s["interval"] == 5
    assert "dev-secret" not in json.dumps(s)                       # the device id stays on the server

    assert alice.post("/api/account/credentials/chatgpt/poll", json={"handle": s["handle"]}).json() == {"pending": True}
    openai.approved = True
    r = alice.post("/api/account/credentials/chatgpt/poll", json={"handle": s["handle"]}).json()
    assert r["pending"] is False
    assert r["credential"]["provider"] == "openai" and r["credential"]["kind"] == "subscription"
    assert r["credential"]["label"] == "ChatGPT subscription" and r["credential"]["is_default"] is True

    ex = openai.exchanged[0]
    assert ex["grant_type"] == ["authorization_code"] and ex["code"] == ["auth-code"] and ex["code_verifier"] == ["ver"]
    assert ex["redirect_uri"] == ["https://auth.openai.com/deviceauth/callback"]
    with db_session() as db:
        auth = json.loads(decrypt(db.query(ModelCredential).one().secret_enc))
    assert auth["OPENAI_API_KEY"] is None and auth["last_refresh"].endswith("Z")
    assert auth["tokens"] == {"id_token": ID_TOKEN, "access_token": "at-1", "refresh_token": "rt-1", "account_id": "acct-1"}


def test_handle_only_works_for_its_owner(make_user, openai):
    alice, bob = make_user("alice"), make_user("bob")
    handle = alice.post("/api/account/credentials/chatgpt/start").json()["handle"]
    openai.approved = True
    r = bob.post("/api/account/credentials/chatgpt/poll", json={"handle": handle})
    assert r.status_code == 400 and "isn't yours" in r.json()["detail"]
    assert bob.post("/api/account/credentials/chatgpt/poll", json={"handle": "garbage"}).status_code == 400


def test_expired_code(make_user, openai, monkeypatch):
    alice = make_user("alice")
    handle = alice.post("/api/account/credentials/chatgpt/start").json()["handle"]
    monkeypatch.setattr(codex_login, "now", lambda: 10**12)
    r = alice.post("/api/account/credentials/chatgpt/poll", json={"handle": handle})
    assert r.status_code == 400 and "expired" in r.json()["detail"]


def test_off_when_subscriptions_are_off(make_user, openai, monkeypatch):
    monkeypatch.setattr(settings(), "allow_subscription_tokens", False)
    assert make_user("alice").post("/api/account/credentials/chatgpt/start").status_code == 403


def test_openai_turned_device_codes_off(make_user, monkeypatch):
    monkeypatch.setattr(codex_login, "http", lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))))
    r = make_user("alice").post("/api/account/credentials/chatgpt/start")
    assert r.status_code == 502 and "auth.json" in r.json()["detail"]
