"""The guides are public markdown, the same files the mayor reads."""

from app import marketplace


def test_anyone_can_read_the_agent_guide(client):
    r = client.get("/api/guides/create-an-agent")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    assert r.text.startswith("# Create an agent in Agent Town")
    assert client.get("/api/guides/create-an-agent.md").text == r.text
    assert client.head("/api/guides/create-an-agent").status_code == 200


def test_the_guide_list_and_an_unknown_guide(client):
    assert [g["url"] for g in client.get("/api/guides").json()] == ["/api/guides/create-an-agent"]
    assert client.get("/api/guides/nope").status_code == 404
    assert client.get("/api/guides/..%2F..%2Fbackend%2Fpyproject.toml").status_code == 404


def test_the_mayor_has_the_same_guide(client):
    mayor = {f["path"]: f["content"] for f in marketplace.catalog()["mayor"]["files"]}
    assert mayor["skills/agent-builder/create-an-agent.md"] == client.get("/api/guides/create-an-agent").text
