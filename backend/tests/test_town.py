"""Agent Town's own tools (app/town.py): the person's mayor proposes agents and colonies (its
agent-builder skill), and nothing is added until the person presses Add."""

from app import sandbox

from .conftest import FakeProvider
from .test_google import rpc


def builder_run(alice, client, monkeypatch):
    """alice's mayor (installed from the market, with its Agent Town tools) in a running chat, in a town
    that has Ava's Assistant colony too."""
    FakeProvider.started = []
    monkeypatch.setattr(sandbox, "provider", lambda name=None: FakeProvider())
    alice.post("/api/account/credentials", json={"provider": "anthropic", "kind": "subscription", "secret": "sk-ant-oat01-" + "x" * 40})
    alice.post("/api/marketplace/ava/install")
    b = alice.post("/api/marketplace/mayor/install").json()["agent"]
    town = next(c for c in alice.get("/api/city").json()["connections"] if c["name"] == "Agent Town")
    assert b["grants"] == [{"connection_id": town["id"], "tool_name": None}]
    alice.post(f"/api/agents/{b['id']}/runs")
    client.cookies.clear()
    client.headers["Authorization"] = f"Bearer {FakeProvider.started[-1][1]}"
    return client, town["id"], client.get("/api/runtime/setup").json()["run_id"]


ASSISTANT = {"ava", "finn", "cleo", "theo", "mayor"}


def call(sb, conn_id, tool, **args):
    return rpc(sb, conn_id, "tools/call", {"name": tool, "arguments": args}).json()["result"]


def waiting(alice, run_id):
    return [e for e in alice.get(f"/api/runs/{run_id}/events").json()["events"] if e["kind"] == "approval"]


def names(alice):
    return {a["name"] for a in alice.get("/api/agents").json()}


def propose(sb, town, name):
    return call(sb, town, "create_agent", name=name, description=f"Does {name} things.", instructions=f"# {name}\n\nDo it well.")


def test_signup_from_the_app_starts_with_only_the_mayor(client):
    r = client.post("/api/auth/signup", json={"email": "bob@example.com", "username": "bob",
                                              "password": "correct horse battery", "starter": True})
    assert r.status_code == 200, r.text
    [mayor] = client.get("/api/agents").json()
    # it builds the rest with them: a skill, Agent Town's own tools, and the guide it teaches from
    assert mayor["name"] == "mayor" and mayor["role"] == "mayor" and mayor["colony_name"] == "" and mayor["team"] == []
    files = {f["path"] for f in client.get(f"/api/agents/{mayor['id']}").json()["files"]}
    assert {"skills/agent-builder/SKILL.md", "town-guide.md"} <= files and len(mayor["grants"]) == 1
    assert client.get("/api/today").json()["suggested"] == [] and client.get("/api/routines").json() == []
    # the ready-made colonies are still a click away in the market, without the builder
    ava = client.post("/api/marketplace/ava/install").json()["agent"]
    assert ava["grants"] == [] and not any(f["path"].startswith("skills/") for f in client.get(f"/api/agents/{ava['id']}").json()["files"])


def test_they_name_their_mayor_at_sign_up(client, make_user):
    def signup(name, user="dee"):
        return client.post("/api/auth/signup", json={"email": f"{user}@example.com", "username": user, "starter": True,
                                                     "password": "correct horse battery", "assistant_name": name})
    assert signup("Maya").status_code == 422                     # a market agent's name
    assert signup("R2-D2").status_code == 422                    # a name, not a code
    assert signup("  Jarvis ").status_code == 200
    [j] = client.get("/api/agents").json()
    assert j["name"] == "Jarvis" and j["slug"] == "mayor" and j["role"] == "mayor"
    md = next(f["content"] for f in client.get(f"/api/agents/{j['id']}").json()["files"] if f["path"] == "AGENT.md")
    assert "name: Jarvis" in md and "You are Jarvis" in md and "Mayor" not in md
    # still the market's mayor: an update keeps the name, the starter doesn't add a second
    client.post("/api/marketplace/mayor/install")
    client.post("/api/marketplace/starter")
    assert [a["name"] for a in client.get("/api/agents").json()] == ["Jarvis"]
    # an empty town names it on the way in too
    eve = make_user("eve")
    assert eve.post("/api/marketplace/starter", json={"assistant_name": "cleo"}).status_code == 422
    eve.post("/api/marketplace/starter", json={"assistant_name": "Friday"})
    assert {a["name"] for a in eve.get("/api/agents").json()} == {"Friday"}


def test_renaming_rewrites_its_instructions_and_its_leads(make_user):
    alice = make_user("alice")
    alice.post("/api/marketplace/ava/install")

    def agents():
        return {a["name"]: a for a in alice.get("/api/agents").json()}

    def md(a):
        return next(f["content"] for f in a["files"] if f["path"] == "AGENT.md")

    finn = agents()["finn"]
    alice.patch(f"/api/agents/{finn['id']}", json={"name": "Felix"})
    now = agents()
    assert "name: Felix" in md(now["Felix"]) and "You are Felix" in md(now["Felix"]) and "Finn" not in md(now["Felix"])
    assert "**Felix**: follow-ups" in md(now["ava"]) and "finn" not in md(now["ava"])
    assert "Felix, Cleo and Theo" in now["ava"]["description"]            # her one-liner too
    alice.patch(f"/api/agents/{now['ava']['id']}", json={"name": "Jarvis"})
    assert "You are Jarvis" in md(agents()["Jarvis"])
    # an agent whose text doesn't call it by name only gets its name: line
    d = alice.post("/api/agents", json={"markdown": "---\nname: data\ndescription: Reads the data.\n---\n\nRead the data.\n"}).json()
    alice.patch(f"/api/agents/{d['id']}", json={"name": "numbers"})
    assert md(agents()["numbers"]) == "---\nname: numbers\ndescription: Reads the data.\n---\n\nRead the data.\n"


def test_signup_without_starter_is_empty(make_user):
    assert make_user("cyd").get("/api/agents").json() == []


def test_an_empty_town_can_get_the_starter_later(make_user):
    alice = make_user("alice")
    assert alice.post("/api/marketplace/starter").json()["agent"]["name"] == "mayor"
    alice.post("/api/marketplace/starter")                       # again: no copies, one connection
    assert names(alice) == {"mayor"}
    assert [c["name"] for c in alice.get("/api/city").json()["connections"]] == ["Agent Town"]


def test_an_agent_is_only_added_when_the_person_presses_add(make_user, client, monkeypatch):
    alice, bob = make_user("alice"), make_user("bob")
    sb, town, run_id = builder_run(alice, client, monkeypatch)
    assert "ava" in call(sb, town, "list_agents")["content"][0]["text"]
    assert "Not added yet" in propose(sb, town, "outreach-writer")["content"][0]["text"]
    assert names(alice) == ASSISTANT
    [e] = waiting(alice, run_id)
    assert e["data"]["type"] == "agent" and e["data"]["state"] == "pending"
    assert bob.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True}).status_code == 404
    assert alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True}).json()["data"]["state"] == "sent"
    assert names(alice) == ASSISTANT | {"outreach-writer"}
    note = [x for x in alice.get(f"/api/runs/{run_id}/events").json()["events"] if x["kind"] == "notice"][-1]
    assert "pressed Add" in note["data"]["text"]
    # a name they already have is refused up front
    assert call(sb, town, "create_agent", name="outreach-writer", description="x", instructions="y")["isError"]


def test_turning_one_down_adds_nothing(make_user, client, monkeypatch):
    alice = make_user("alice")
    sb, town, run_id = builder_run(alice, client, monkeypatch)
    propose(sb, town, "nope")
    [e] = waiting(alice, run_id)
    assert alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": False}).json()["data"]["state"] == "declined"
    assert names(alice) == ASSISTANT


def test_a_colony_needs_its_agents_first_then_takes_them(make_user, client, monkeypatch):
    alice = make_user("alice")
    sb, town, run_id = builder_run(alice, client, monkeypatch)
    call(sb, town, "create_colony", name="Outreach", about="Posts and cold emails", lead="lead-one", members=["writer"])
    [col] = waiting(alice, run_id)
    r = alice.post(f"/api/runs/{run_id}/approvals/{col['id']}", json={"send": True})
    assert r.status_code == 409 and "lead-one, writer" in r.json()["detail"]
    for n in ("lead-one", "writer"):
        propose(sb, town, n)
    for e in waiting(alice, run_id):
        if e["data"]["type"] == "agent":
            alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True})
    assert alice.post(f"/api/runs/{run_id}/approvals/{col['id']}", json={"send": True}).json()["data"]["state"] == "sent"
    agents = {a["name"]: a for a in alice.get("/api/agents").json()}
    lead = agents["lead-one"]
    assert lead["colony_name"] == "Outreach" and lead["team"] == [agents["writer"]["id"]]
    # an agent proposed into that colony joins it when added
    call(sb, town, "create_agent", name="poster", description="Posts.", instructions="Post.", colony="outreach")
    e = waiting(alice, run_id)[-1]
    alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True})
    agents = {a["name"]: a for a in alice.get("/api/agents").json()}
    assert agents["poster"]["id"] in agents["lead-one"]["team"]


def test_an_empty_colony_is_listed_and_filled_by_a_colony_with_its_name(make_user, client, monkeypatch):
    alice = make_user("alice")
    sb, town, run_id = builder_run(alice, client, monkeypatch)
    alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Home", "about": "Bills and errands"}, {"name": "Gym"}]})
    assert '"Home"' in call(sb, town, "list_agents")["content"][0]["text"]
    # no lead to join yet: told how to fill it instead
    r = call(sb, town, "create_agent", name="biller", description="Pays bills.", instructions="Pay.", colony="home")
    assert r["isError"] and "create_colony" in r["content"][0]["text"]
    for n in ("biller", "errands"):
        propose(sb, town, n)
    call(sb, town, "create_colony", name="home", lead="biller", members=["errands"])
    for e in waiting(alice, run_id):
        alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True})
    lead = next(a for a in alice.get("/api/agents").json() if a["name"] == "biller")
    assert lead["colony_name"] == "Home" and lead["colony_about"] == "Bills and errands"   # its note carries over
    assert alice.get("/api/city").json()["empty_colonies"] == [{"name": "Gym", "about": ""}]


def test_bad_calls_and_other_peoples_towns(make_user, client, monkeypatch):
    alice, bob = make_user("alice"), make_user("bob")
    bob.post("/api/marketplace/starter")
    sb, town, _ = builder_run(alice, client, monkeypatch)
    assert call(sb, town, "create_agent", name="", description="x", instructions="y")["isError"]
    assert call(sb, town, "create_colony", name="X", lead="a", members="b")["isError"]
    assert not call(sb, town, "create_colony", name="X", lead="a", members=["A "]).get("isError")   # a colony of one
    assert "ava" in call(sb, town, "list_agents")["content"][0]["text"]
    bob_town = next(c for c in bob.get("/api/city").json()["connections"] if c["name"] == "Agent Town")
    assert rpc(sb, bob_town["id"], "tools/list").status_code == 404


def test_an_empty_colony_can_be_proposed_and_filled_in_later(make_user, client, monkeypatch):
    alice = make_user("alice")
    sb, town, run_id = builder_run(alice, client, monkeypatch)
    assert call(sb, town, "create_colony", name="Sales", members=["finn"]).get("isError")      # members need a lead
    assert "already leads" in call(sb, town, "create_colony", name="assistant")["content"][0]["text"]
    assert "Not added yet" in call(sb, town, "create_colony", name="Sales", about="Outreach and deals")["content"][0]["text"]
    [e] = waiting(alice, run_id)
    assert (e["data"]["lead"], e["data"]["members"]) == ("", [])
    alice.post(f"/api/runs/{run_id}/approvals/{e['id']}", json={"send": True})
    assert alice.get("/api/city").json()["empty_colonies"] == [{"name": "Sales", "about": "Outreach and deals"}]
    assert names(alice) == ASSISTANT                                                         # no agent made for it
    assert "already have an empty colony" in call(sb, town, "create_colony", name="sales")["content"][0]["text"]
    # its agents come later: a colony with its name fills it in
    propose(sb, town, "closer")
    [a] = [x for x in waiting(alice, run_id) if x["data"]["state"] == "pending"]
    alice.post(f"/api/runs/{run_id}/approvals/{a['id']}", json={"send": True})
    call(sb, town, "create_colony", name="SALES", lead="closer")
    [c] = [x for x in waiting(alice, run_id) if x["data"]["state"] == "pending"]
    alice.post(f"/api/runs/{run_id}/approvals/{c['id']}", json={"send": True})
    city = alice.get("/api/city").json()
    assert city["empty_colonies"] == [] and next(x for x in city["agents"] if x["name"] == "closer")["colony_name"] == "Sales"
