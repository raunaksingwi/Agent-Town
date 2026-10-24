"""Signing in to Agent Town with Google: new accounts, existing ones, and changing the @name it picked.
Google is faked as in test_google.py."""

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import User

from .test_google import fake_google  # noqa: F401  (the fixture)


def start(c, assistant=""):
    r = c.get("/api/auth/google" + (f"?assistant={assistant}" if assistant else ""), follow_redirects=False)
    assert r.status_code == 303, r.text
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["redirect_uri"] == ["http://testserver/api/connect/google/callback"]
    assert q["scope"] == ["openid email profile"] and "access_type" not in q     # who they are, nothing kept
    return q["state"][0]


def finish(c, state):
    return c.get(f"/api/connect/google/callback?state={state}&code=the-code", follow_redirects=False)


def test_options(client, fake_google):  # noqa: F811
    assert client.get("/api/auth/options").json() == {"google": True, "password_signup": True}


def test_options_without_a_google_client(client):
    assert client.get("/api/auth/options").json() == {"google": False, "password_signup": True}
    assert client.get("/api/auth/google", follow_redirects=False).status_code == 404


def test_a_new_account_gets_a_name_and_its_mayor(db_session, fake_google):  # noqa: F811
    c = TestClient(app)
    r = finish(c, start(c, assistant="Juno"))
    assert r.headers["location"] == "http://testserver/?signed_up=1"
    me = c.get("/api/auth/me").json()
    assert me["username"] == "alice" and me["email"] == "alice@example.com"
    assert me["google"] and not me["has_password"]
    agents = c.get("/api/city").json()["agents"]
    assert [(a["slug"], a["name"], a["role"]) for a in agents] == [("mayor", "Juno", "mayor")]
    # no password means the password form can't get in
    assert c.post("/api/auth/login", json={"login": "alice", "password": ""}).status_code == 401


def test_a_bad_assistant_name_is_refused_up_front(client, fake_google):  # noqa: F811
    r = client.get("/api/auth/google?assistant=123", follow_redirects=False)
    assert r.status_code == 303 and "signin_error" in r.headers["location"]


def test_signing_in_again_finds_the_same_account_even_after_a_rename(db_session, fake_google):  # noqa: F811
    c = TestClient(app)
    finish(c, start(c))
    assert c.patch("/api/account/username", json={"username": "ally"}).json()["username"] == "ally"
    fake_google.person = {**fake_google.person, "email": "alice@new.example.com"}   # their Google email changed too
    again = TestClient(app)
    assert finish(again, start(again)).headers["location"] == "http://testserver/"
    assert again.get("/api/auth/me").json()["username"] == "ally"


def test_an_unverified_password_account_is_taken_over_by_its_emails_owner(make_user, fake_google):  # noqa: F811
    # someone signed up with alice@example.com first (nobody checked it was theirs) and made a token
    squatter = make_user("alice")
    their_id = squatter.get("/api/auth/me").json()["id"]
    token = squatter.post("/api/account/tokens", json={"name": "keep a way in"}).json()["token"]
    c = TestClient(app)                                     # the real alice, with Google
    assert finish(c, start(c)).headers["location"] == "http://testserver/"
    me = c.get("/api/auth/me").json()
    assert me["id"] == their_id and me["google"] and not me["has_password"]
    # every way the squatter had in is gone
    assert squatter.get("/api/auth/me").json() is None
    assert TestClient(app).post("/api/auth/login", json={"login": "alice", "password": "correct horse battery"}).status_code == 401
    assert TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_a_verified_account_keeps_its_password_when_google_links(db_session, make_user, fake_google):  # noqa: F811
    old = make_user("alice")
    with db_session() as db:
        db.query(User).filter_by(username="alice").one().email_verified_at = datetime.now(timezone.utc)   # say, an emailed link
        db.commit()
    c = TestClient(app)
    finish(c, start(c))
    me = c.get("/api/auth/me").json()
    assert me["google"] and me["has_password"] and old.get("/api/auth/me").json()["id"] == me["id"]


def test_names_dont_clash(make_user, fake_google):  # noqa: F811
    make_user("alice")                                      # alice@example.com…
    fake_google.person = {**fake_google.person, "sub": "g-other", "email": "alice.l@example.com"}
    c = TestClient(app)
    finish(c, start(c))
    assert c.get("/api/auth/me").json()["username"] == "alice-2"


def test_an_unconfirmed_email_is_refused(db_session, fake_google):  # noqa: F811
    fake_google.person = {**fake_google.person, "email_verified": False}
    c = TestClient(app)
    assert "signin_error" in finish(c, start(c)).headers["location"]
    assert c.get("/api/auth/me").json() is None


def test_the_callback_must_come_back_to_the_same_browser(db_session, fake_google):  # noqa: F811
    attacker, victim = TestClient(app), TestClient(app)
    r = finish(victim, start(attacker))      # the attacker's half-done sign-in, finished in the victim's browser
    assert "signin_error" in r.headers["location"] and victim.get("/api/auth/me").json() is None


def test_renaming(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    assert alice.patch("/api/account/username", json={"username": "bob"}).status_code == 409
    assert alice.patch("/api/account/username", json={"username": "No Spaces"}).status_code == 422
    assert alice.patch("/api/account/username", json={"username": "alice-l"}).json()["username"] == "alice-l"
    assert bob.post("/api/auth/login", json={"login": "alice-l", "password": "correct horse battery"}).status_code == 200


def test_deleting_an_account_with_no_password_asks_for_the_name(db_session, fake_google):  # noqa: F811
    c = TestClient(app)
    finish(c, start(c))
    assert c.request("DELETE", "/api/account", json={"username": "bob"}).status_code == 403
    assert c.request("DELETE", "/api/account", json={"username": "@alice"}).json() == {"ok": True}


SIGNUP = {"email": "sam@example.com", "username": "sam", "password": "correct horse battery"}


def test_password_signup_can_be_turned_off(make_user, client, fake_google, monkeypatch):  # noqa: F811
    old = make_user("bob")                                  # made while it was on
    monkeypatch.setattr(settings(), "password_signup", False)
    assert client.get("/api/auth/options").json() == {"google": True, "password_signup": False}
    assert client.post("/api/auth/signup", json=SIGNUP).status_code == 403
    # an account that already has a password still signs in with it
    assert TestClient(app).post("/api/auth/login", json={"login": "bob", "password": "correct horse battery"}).status_code == 200
    assert old.get("/api/auth/me").json()["username"] == "bob"
    c = TestClient(app)                                     # and Google still makes new accounts
    assert finish(c, start(c)).headers["location"] == "http://testserver/?signed_up=1"


def test_only_invited_emails_make_accounts(make_user, client, fake_google, monkeypatch):  # noqa: F811
    make_user("bob")                                        # bob@example.com, here before the list
    monkeypatch.setattr(settings(), "allowed_emails", "Sam@Example.com, @partner.co")
    r = client.post("/api/auth/signup", json={**SIGNUP, "email": "eve@example.com", "username": "eve"})
    assert r.status_code == 403 and "invite-only" in r.json()["detail"]
    assert client.post("/api/auth/signup", json=SIGNUP).status_code == 200                   # listed, any case
    other = TestClient(app)
    assert other.post("/api/auth/signup", json={**SIGNUP, "email": "kim@partner.co", "username": "kim"}).status_code == 200
    # a domain entry is the whole domain, not one that ends the same way
    r = other.post("/api/auth/signup", json={**SIGNUP, "email": "x@evilpartner.co", "username": "xx1"})
    assert r.status_code == 403
    # Google: alice@example.com isn't listed, so no account is made
    c = TestClient(app)
    assert "invite-only" in finish(c, start(c)).headers["location"].replace("+", " ").replace("%20", " ")
    assert c.get("/api/auth/me").json() is None
    # existing accounts aren't locked out
    assert TestClient(app).post("/api/auth/login", json={"login": "bob", "password": "correct horse battery"}).status_code == 200
