"""The agent market (agents/ at the repo root). The first two tests are the contribution checks:
every agent there must load cleanly, and none may carry secrets or personal details."""

import re

import pytest

from app import marketplace

CATALOG = marketplace.catalog()
NAMES = {e["name"] for e in CATALOG.values()}

SECRETS = re.compile(
    r"sk-ant-[a-z]{3}\d{2}-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|ghp_[A-Za-z0-9]{30,}|xox[abp]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bak-[A-Za-z0-9]{16,}|\bas-[A-Za-z0-9]{16,}")
PERSONAL = re.compile(r"[\w.+-]+@(?!example\.(com|org))[\w-]+\.[\w.]+|/Users/[^/\s]+|/home/[^/\s]+|\+?\d[\d ()-]{8,}\d")


def test_the_market_is_not_empty():
    assert len(CATALOG) >= 5


@pytest.mark.parametrize("slug", sorted(CATALOG))
def test_market_agent_is_valid(slug):
    entry = CATALOG[slug]
    assert marketplace.problems(entry, NAMES) == [], f"agents/{slug}"
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]+", entry["name"]), "name: lowercase words joined by hyphens"
    assert entry["name"] == slug, "the folder is named after the agent"
    assert 10 <= len(entry["description"]) <= 200, "description: one line, up to 200 characters"


@pytest.mark.parametrize("slug", sorted(CATALOG))
def test_market_agent_has_no_secrets_or_personal_details(slug):
    for f in CATALOG[slug]["files"]:
        assert not SECRETS.search(f["content"]), f"agents/{slug}/{f['path']} looks like it holds a secret"
        m = PERSONAL.search(f["content"])
        assert not m, f"agents/{slug}/{f['path']} has something personal: {m.group(0)!r} (use example.com)"


def test_install_adds_the_agent_and_its_team(make_user):
    alice = make_user("alice")
    market = alice.get("/api/marketplace").json()
    assert {m["slug"] for m in market} == set(CATALOG) and not any(m["installed"] for m in market)
    lead = next(e for e in CATALOG.values() if e["team"])
    r = alice.post(f"/api/marketplace/{lead['slug']}/install").json()
    assert sorted(r["added"]) == sorted([lead["name"], *lead["team"]])
    a = r["agent"]
    assert a["name"] == lead["name"] and a["building"] == lead["building"] and len(a["team"]) == len(lead["team"])
    assert len(alice.get("/api/agents").json()) == 1 + len(lead["team"])
    # installing again updates instead of copying
    alice.post(f"/api/marketplace/{lead['slug']}/install")
    assert len(alice.get("/api/agents").json()) == 1 + len(lead["team"])
    assert all(m["installed"] for m in alice.get("/api/marketplace").json() if m["name"] in r["added"])


def test_a_colony_can_be_renamed(make_user):
    alice = make_user("alice")
    lead = alice.post("/api/marketplace/maya/install").json()["agent"]
    assert lead["colony_name"] == "Company"                     # from its AGENT.md
    r = alice.patch(f"/api/agents/{lead['id']}", json={"colony_name": "  Outreach ", "colony_about": "Posts and cold emails"})
    assert r.status_code == 200 and r.json()["colony_name"] == "Outreach" and r.json()["colony_about"] == "Posts and cold emails"
    assert alice.patch(f"/api/agents/{lead['id']}", json={"colony_name": "x" * 61}).status_code == 422


def test_install_needs_a_real_slug_and_a_user(client, make_user):
    assert client.get("/api/marketplace").status_code == 401
    alice = make_user("alice")
    assert alice.post("/api/marketplace/no-such-agent/install").status_code == 404
    assert alice.post("/api/marketplace/..%2Fsecrets/install").status_code in (404, 405)   # never reaches a file
