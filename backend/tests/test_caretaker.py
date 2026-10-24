"""The caretaker (app/caretaker.py): Agent Town's own helper. The Messages API is faked with a script of
replies, so these test what its tools do to the town, Undo, Add, and that it only ever sees and changes
the person's own things."""

import json
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaTextBlock, BetaToolUseBlock

from app import caretaker
from app.model_check import Checked
from app.routers import account as account_router

from .conftest import AGENT_MD

KEY = "sk-ant-api03-" + "k" * 40
OAT = "sk-ant-oat01-" + "x" * 40


class FakeClaude:
    """Answers each call with the next scripted reply: a list of ("text", str) or ("tool", name, input)."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        blocks, n = [], len(self.calls)
        for i, part in enumerate(self.replies.pop(0) if self.replies else [("text", "Done.")]):
            if part[0] == "text":
                blocks.append(BetaTextBlock(type="text", text=part[1]))
            else:
                blocks.append(BetaToolUseBlock(type="tool_use", id=f"tu_{n}_{i}", name=part[1], input=part[2]))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return SimpleNamespace(content=blocks, stop_reason=stop)


@pytest.fixture
def claude(monkeypatch):
    holder = {}

    def use(*replies):
        holder["fake"] = FakeClaude(*replies)
        return holder["fake"]
    monkeypatch.setattr(caretaker.anthropic, "Anthropic", lambda **kw: holder["fake"])
    return use


def with_key(c, monkeypatch, secret=KEY, kind="api_key", provider="anthropic"):
    monkeypatch.setattr(account_router.model_check, "check", lambda *a, **k: Checked("valid", "ok"))
    assert c.post("/api/account/credentials", json={"provider": provider, "kind": kind, "secret": secret}).status_code == 200


def agent(c, name, color="#3f8fd2"):
    return c.post("/api/agents", json={"markdown": AGENT_MD.replace("reel-writer", name), "color": color}).json()


def layout(*things):
    """What the browser sends: each building's corner and size, in tiles from the square."""
    return [{"key": k, "kind": k.split(":")[0], "label": k, "x": x, "y": y, "w": 3, "h": 3} for k, x, y in things]


def say(c, text, *things):
    return c.post("/api/caretaker/messages", json={"text": text, "layout": layout(*things), "theme": "retro"})


def last(r):
    assert r.status_code == 200, r.text
    return r.json()["turns"][-1]


def test_it_needs_a_claude(make_user, monkeypatch):
    alice = make_user("alice")
    state = alice.get("/api/caretaker").json()
    assert state["ready"] is False and "connect your Claude" in state["why"]
    r = say(alice, "hi")
    assert r.status_code == 409
    with_key(alice, monkeypatch, "sk-" + "o" * 40, provider="openai")              # ChatGPT can't run it yet
    assert alice.get("/api/caretaker").json()["ready"] is False
    with_key(alice, monkeypatch, OAT, "subscription")                               # a Claude subscription can
    assert alice.get("/api/caretaker").json()["via"] == "subscription"
    with_key(alice, monkeypatch)                                                     # and an API key is preferred
    assert alice.get("/api/caretaker").json()["via"] == "api_key"


def test_it_answers_with_the_town_and_cached_guides(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    a = agent(alice, "maya")
    alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Garden club"}]})
    fake = claude([("text", "Maya lives by the square.")])
    t = last(say(alice, "where is maya?", (f"agent:{a['id']}", 4, 2)))
    assert t["reply"] == "Maya lives by the square." and t["changed"] is False
    kw = fake.calls[0]
    assert kw["model"] == caretaker.MODEL and kw["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "CARETAKER.md" in kw["system"][-1]["text"] and "AGENTS.md" in kw["system"][-1]["text"]
    town = kw["messages"][-1]["content"][0]["text"]
    assert f'"agent:{a["id"]}"' in town and '"maya"' in town and KEY not in str(kw)
    assert '"empty_colonies"' in town and '"Garden club"' in town
    # the next message resends this one as it was: the model API wants history unchanged
    fake2 = claude([("text", "Still there.")])
    say(alice, "and now?")
    assert fake2.calls[0]["messages"][:2] == [kw["messages"][-1], {"role": "assistant", "content": [{"type": "text", "text": "Maya lives by the square."}]}]


def test_moving_buildings_and_undo(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    a, b = agent(alice, "maya"), agent(alice, "finn")
    ka, kb = f"agent:{a['id']}", f"agent:{b['id']}"
    here = [(ka, 0, 10), (kb, 20, 10)]
    claude([("tool", "move_buildings", {"moves": [{"key": ka, "x": 30, "y": 5}]})], [("text", "Moved Maya.")])
    t = last(say(alice, "move maya east", *here))
    assert alice.get("/api/city").json()["town"] == {ka: [30.0, 5.0]}
    assert t["changed"] and t["can_undo"]

    # a spot on top of another building is refused, and nothing moves
    fake = claude([("tool", "move_buildings", {"moves": [{"key": kb, "x": 30.5, "y": 5}]})], [("text", "That spot's taken.")])
    t2 = last(say(alice, "put finn on maya", (ka, 30, 5), (kb, 20, 10)))
    result = fake.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "would stand on" in result["content"]
    assert t2["changed"] is False and alice.get("/api/city").json()["town"] == {ka: [30.0, 5.0]}

    assert alice.post(f"/api/caretaker/turns/{t['id']}/undo").status_code == 200
    turns = alice.get("/api/caretaker").json()["turns"]
    assert turns[0]["undone"] and not turns[0]["can_undo"]
    assert alice.get("/api/city").json()["town"] == {}
    assert alice.post(f"/api/caretaker/turns/{t['id']}/undo").status_code == 409        # once is enough


def colony_map(lead, member):
    """A colony's block as the browser sends it: the area (box, corner, room), then its houses in it."""
    return [{"key": "colony:7", "kind": "area", "label": "Nick's colony", "x": 10, "y": -5, "w": 14, "h": 12,
             "corner": [10, -5], "room": [8, -8, 20, 18]},
            {"key": lead, "kind": "agent", "label": "nick", "area": "colony:7", "x": 12, "y": -2, "w": 3, "h": 3},
            {"key": member, "kind": "agent", "label": "finn", "area": "colony:7", "x": 18, "y": -2, "w": 3, "h": 3}]


def test_colonies_are_areas_with_their_own_corner(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    a, b = agent(alice, "nick"), agent(alice, "finn")
    ka, kb = f"agent:{a['id']}", f"agent:{b['id']}"
    assert alice.put(f"/api/agents/{a['id']}/team", json={"member_ids": [b["id"]]}).status_code == 200
    send = lambda text: alice.post("/api/caretaker/messages", json={"text": text, "layout": colony_map(ka, kb)})  # noqa: E731
    fake = claude([("tool", "move_buildings", {"moves": [{"key": kb, "x": 2, "y": 9}]})], [("text", "Moved.")])
    t = last(send("put finn under nick"))
    # it's shown the block as a box, with each house counted from the block's corner
    text = fake.calls[0]["messages"][-1]["content"][0]["text"]
    block = next(m for m in json.loads(text.split("<town>")[1].split("</town>")[0])["map"] if m["key"] == "colony:7")
    assert block["room"] == {"x": -2, "y": -3, "w": 20, "h": 18} and block["box"]["x"] == 0
    assert {"key": ka, "label": "nick", "x": 2, "y": 3, "w": 3, "h": 3, "moved": False} in block["buildings"]
    # and what's saved is the spot in the block, so the house moves with its colony
    assert t["changed"] and alice.get("/api/city").json()["town"] == {kb: [2.0, 9.0]}

    # a house can't leave its colony's room
    fake = claude([("tool", "move_buildings", {"moves": [{"key": ka, "x": 30, "y": 0}]})], [("text", "Can't.")])
    last(send("move nick far away"))
    result = fake.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "would leave its area" in result["content"]

    # its lead stays nearest the square (0, 0): a member can't go in front of it, nor the lead behind its team
    for move in ({"key": kb, "x": -1.5, "y": -3}, {"key": ka, "x": 12, "y": 9}):
        fake = claude([("tool", "move_buildings", {"moves": [move]})], [("text", "Can't.")])
        last(send("swap them"))
        result = fake.calls[1]["messages"][-1]["content"][0]
        assert result["is_error"] and "lead always stands nearest the square" in result["content"]

    # tidying a colony puts everything in it back where the map places it
    claude([("tool", "reset_layout", {"keys": ["colony:7"]})], [("text", "Tidied.")])
    last(send("tidy nick's colony"))
    assert alice.get("/api/city").json()["town"] == {}


def test_stalls_and_unknown_buildings_cant_move(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    fake = claude([("tool", "move_buildings", {"moves": [{"key": "station:1", "x": 1, "y": 1}]}),
                   ("tool", "move_buildings", {"moves": [{"key": "agent:999", "x": 1, "y": 1}]})], [("text", "Can't.")])
    say(alice, "move things", ("station:1", 0, 0))
    errors = [r["content"] for r in fake.calls[1]["messages"][-1]["content"]]
    assert "can't be moved" in errors[0] and "No agent" in errors[1]
    assert alice.get("/api/city").json()["town"] == {}


def test_renaming_and_restyling_an_agent_undoes_whole(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    a = agent(alice, "maya")
    claude([("tool", "update_agent", {"agent": f"agent:{a['id']}", "name": "mira", "color": "#d1694f", "building": "tower"}),
            ("tool", "set_map_style", {"style": "fantasy"})], [("text", "Done.")])
    t = last(say(alice, "call maya mira, make her a red tower, and make the map fantasy"))
    assert {"type": "theme", "style": "fantasy"} in t["actions"]
    got = alice.get(f"/api/agents/{a['id']}").json()
    assert (got["name"], got["color"], got["building"]) == ("mira", "#d1694f", "tower")
    assert "name: mira" in next(f["content"] for f in got["files"] if f["path"] == "AGENT.md")
    assert alice.get("/api/city").json()["map_style"] == "fantasy"
    alice.post(f"/api/caretaker/turns/{t['id']}/undo")
    got = alice.get(f"/api/agents/{a['id']}").json()
    assert (got["name"], got["color"], got["building"]) == ("maya", "#3f8fd2", "")
    assert "name: maya" in next(f["content"] for f in got["files"] if f["path"] == "AGENT.md")
    assert alice.get("/api/city").json()["map_style"] == ""


def test_changing_a_colony_and_undo(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    lead, x, y, z = (agent(alice, n) for n in ("lead", "xavi", "yara", "zoe"))
    other = agent(alice, "other")
    alice.put(f"/api/agents/{lead['id']}/team", json={"member_ids": [x["id"]]})
    alice.put(f"/api/agents/{other['id']}/team", json={"member_ids": [y["id"], z["id"]]})
    fake = claude([("tool", "update_colony", {"lead": f"agent:{lead['id']}", "name": "Studio", "about": "Makes videos",
                                              "members": [f"agent:{x['id']}", f"agent:{y['id']}"]}),
                   ("tool", "update_colony", {"lead": f"agent:{z['id']}", "name": "Nope"})], [("text", "Done.")])
    t = last(say(alice, "move yara into the lead's colony and call it Studio"))
    assert "propose_colony" in fake.calls[1]["messages"][-1]["content"][1]["content"]   # zoe leads nothing: that's a proposal
    got = {a["id"]: a for a in alice.get("/api/agents").json()}
    assert sorted(got[lead["id"]]["team"]) == sorted([x["id"], y["id"]]) and got[other["id"]]["team"] == [z["id"]]
    assert (got[lead["id"]]["colony_name"], got[lead["id"]]["colony_about"]) == ("Studio", "Makes videos")
    alice.post(f"/api/caretaker/turns/{t['id']}/undo")
    got = {a["id"]: a for a in alice.get("/api/agents").json()}
    assert got[lead["id"]]["team"] == [x["id"]] and sorted(got[other["id"]]["team"]) == sorted([y["id"], z["id"]])
    assert got[lead["id"]]["colony_name"] == ""


def test_a_new_agent_waits_for_add(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    claude([("tool", "propose_agent", {"name": "scout", "description": "Finds leads.", "instructions": "# Scout\n\nFind leads."}),
            ("tool", "propose_agent", {"name": "skip", "description": "Skips.", "instructions": "# Skip"})], [("text", "Two ideas.")])
    t = last(say(alice, "I need help finding leads"))
    assert [p["data"]["state"] for p in t["proposals"]] == ["pending", "pending"] and t["changed"] is False
    assert alice.get("/api/agents").json() == []                     # nothing until they press Add
    t = last(alice.post(f"/api/caretaker/turns/{t['id']}/proposals/0", json={"add": True}))
    t = last(alice.post(f"/api/caretaker/turns/{t['id']}/proposals/1", json={"add": False}))
    assert [p["data"]["state"] for p in t["proposals"]] == ["sent", "declined"]
    assert [a["name"] for a in alice.get("/api/agents").json()] == ["scout"]
    assert alice.post(f"/api/caretaker/turns/{t['id']}/proposals/0", json={"add": True}).status_code == 409
    # and it hears what they chose, once
    fake = claude([("text", "Scout is in.")])
    say(alice, "thanks")
    news = fake.calls[0]["messages"][-1]["content"][1]["text"]
    assert "pressed Add: the agent scout" in news and "didn't add the agent skip" in news
    fake = claude([("text", "ok")])
    say(alice, "bye")
    assert len(fake.calls[0]["messages"][-1]["content"]) == 2         # the town and their words, no news


def test_a_new_colony_by_keys_and_proposed_names(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    nick, neha = agent(alice, "nick"), agent(alice, "neha")
    claude([("tool", "propose_colony", {"name": "Personal", "lead": f"agent:{neha['id']}", "members": [f"agent:{neha['id']}"]}),
            ("tool", "propose_agent", {"name": "scout", "description": "Finds leads.", "instructions": "# Scout"}),
            ("tool", "propose_colony", {"name": "Company", "lead": f"agent:{nick['id']}", "members": ["scout"]})],
           [("text", "Press Add on all three.")])
    t = last(say(alice, "give neha her own colony, and nick a scout"))
    assert [p["data"].get("members") for p in t["proposals"]] == [[], None, ["scout"]]   # neha: a colony of one
    assert t["proposals"][2]["data"]["lead"] == "nick"
    for i in (0, 1, 2):
        t = last(alice.post(f"/api/caretaker/turns/{t['id']}/proposals/{i}", json={"add": True}))
    got = {a["name"]: a for a in alice.get("/api/agents").json()}
    assert got["nick"]["team"] == [got["scout"]["id"]] and got["nick"]["colony_name"] == "Company"
    assert (got["neha"]["team"], got["neha"]["colony_name"]) == ([], "Personal")
    fake = claude([("text", "ok")])
    say(alice, "where is everyone")
    town = fake.calls[0]["messages"][-1]["content"][0]["text"]
    assert '"leads_colony": "Personal"' in town


def test_a_colony_of_one_joining_another_is_no_longer_one(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    nick, neha, x = agent(alice, "nick"), agent(alice, "neha"), agent(alice, "xavi")
    alice.put(f"/api/agents/{nick['id']}/team", json={"member_ids": [x["id"]]})
    alice.patch(f"/api/agents/{neha['id']}", json={"colony_name": "Personal"})
    claude([("tool", "update_colony", {"lead": f"agent:{nick['id']}", "members": [f"agent:{x['id']}", f"agent:{neha['id']}"]})],
           [("text", "Done.")])
    t = last(say(alice, "put neha in nick's colony"))
    got = {a["name"]: a for a in alice.get("/api/agents").json()}
    assert sorted(got["nick"]["team"]) == sorted([x["id"], neha["id"]]) and got["neha"]["colony_name"] == ""
    alice.post(f"/api/caretaker/turns/{t['id']}/undo")
    got = {a["name"]: a for a in alice.get("/api/agents").json()}
    assert got["nick"]["team"] == [x["id"]] and got["neha"]["colony_name"] == "Personal"


def test_other_peoples_things(make_user, monkeypatch, claude):
    alice, bob = make_user("alice"), make_user("bob")
    with_key(alice, monkeypatch)
    with_key(bob, monkeypatch)
    secret = agent(bob, "secret")
    fake = claude([("tool", "update_agent", {"agent": f"agent:{secret['id']}", "name": "mine"}),
                   ("tool", "focus", {"key": f"agent:{secret['id']}"})], [("text", "Can't.")])
    t = last(say(alice, "rename bob's agent"))
    assert all(r["is_error"] for r in fake.calls[1]["messages"][-1]["content"])
    assert "secret" not in fake.calls[0]["messages"][-1]["content"][0]["text"]
    assert bob.get(f"/api/agents/{secret['id']}").json()["name"] == "secret"
    assert bob.post(f"/api/caretaker/turns/{t['id']}/undo").status_code == 404
    assert bob.post(f"/api/caretaker/turns/{t['id']}/proposals/0", json={"add": True}).status_code == 404
    assert bob.get("/api/caretaker").json()["turns"] == []


def test_screens_and_focus_go_to_the_browser(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    a = agent(alice, "maya")
    claude([("tool", "open_screen", {"screen": "apps"}), ("tool", "open_screen", {"screen": "setup", "agent": f"agent:{a['id']}"}),
            ("tool", "focus", {"key": f"agent:{a['id']}"})], [("text", "Press Connect next to Gmail.")])
    t = last(say(alice, "how do I connect gmail?", (f"agent:{a['id']}", 0, 0)))
    assert t["actions"] == [{"type": "open", "screen": "apps", "label": "Connect apps"},
                            {"type": "open", "screen": "setup", "label": "Make it your own: maya", "agent_id": a["id"]},
                            {"type": "focus", "key": f"agent:{a['id']}"}]


def test_start_over_and_api_errors(make_user, monkeypatch, claude):
    import anthropic
    import httpx
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    claude([("text", "hello")])
    say(alice, "hi")
    assert alice.post("/api/caretaker/start-over").json() == {"turns": []}
    assert alice.get("/api/caretaker").json()["turns"] == []
    fake = claude([("text", "fresh")])
    say(alice, "hi again")
    assert len(fake.calls[0]["messages"]) == 1                       # the old conversation isn't sent

    def bad_key(**kw):
        raise anthropic.AuthenticationError("no", response=httpx.Response(401, request=httpx.Request("POST", "https://x")), body=None)
    fake = claude()
    fake.beta.messages.create = bad_key
    r = say(alice, "hello?")
    assert r.status_code == 502 and "didn't accept your API key" in r.json()["detail"]
    assert len(alice.get("/api/caretaker").json()["turns"]) == 1     # a failed message leaves nothing behind


def test_map_style_is_kept_with_the_account(make_user):
    alice = make_user("alice")
    assert alice.get("/api/city").json()["map_style"] == ""
    assert alice.patch("/api/account/preferences", json={"map_style": "office"}).json() == {"map_style": "office"}
    assert alice.get("/api/city").json()["map_style"] == "office"
    assert alice.patch("/api/account/preferences", json={"map_style": "neon"}).status_code == 422
    assert alice.patch("/api/account/preferences", json={"map_style": "blocks"}).status_code == 422   # a look that's gone


def test_the_built_in_town_connection_checks_as_connected(make_user):
    alice = make_user("alice")
    alice.post("/api/marketplace/mayor/install")
    town = next(c for c in alice.get("/api/city").json()["connections"] if c["name"] == "Agent Town")
    assert alice.post(f"/api/mcp/{town['id']}/check").json()["status"] == "connected"


# ---- on a subscription: its own sandbox, running Claude Code --------------------------------

@pytest.fixture
def boxes(monkeypatch):
    from app import sandbox

    from .test_runs import FakeProvider
    FakeProvider.started, FakeProvider.stopped, FakeProvider.dead = [], [], set()
    monkeypatch.setattr(sandbox, "provider", lambda name=None: FakeProvider())
    return FakeProvider


def sandbox_client(token):
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def rpc(sb, method, params=None):
    return sb.post("/api/runtime/caretaker", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).json()


def test_on_a_subscription_it_works_in_its_own_sandbox(make_user, monkeypatch, boxes):
    alice = make_user("alice")
    with_key(alice, monkeypatch, OAT, "subscription")
    a = agent(alice, "maya")
    ka = f"agent:{a['id']}"
    t = last(say(alice, "move maya east", (ka, 0, 10)))
    assert t["state"] == "working" and t["reply"] == ""
    [(run_id, token)] = boxes.started
    sb = sandbox_client(token)

    setup = sb.get("/api/runtime/setup").json()
    m = setup["manifest"]
    assert m["kind"] == "caretaker" and "CARETAKER.md" in m["instructions"] and m["files"] == []
    assert setup["credential"] == {"provider": "anthropic", "kind": "subscription", "secret": OAT,
                                   "model": caretaker.MODEL, "thinking": caretaker.EFFORT}
    assert m["tools"][0]["url"].endswith("/api/runtime/caretaker") and OAT not in str(m)
    assert alice.get("/api/runs/active").json() == []                      # it's not an agent on the map
    [msg] = sb.get("/api/runtime/inbox?after=0").json()["messages"]
    assert "<town>" in msg["text"] and msg["text"].endswith("move maya east")

    # a second message waits for this one
    assert say(alice, "and finn?").status_code == 429

    # Claude Code calls its tools over MCP; they act on this message's turn
    assert "move_buildings" in {x["name"] for x in rpc(sb, "tools/list")["result"]["tools"]}
    res = rpc(sb, "tools/call", {"name": "move_buildings", "arguments": {"moves": [{"key": ka, "x": 30, "y": 5}]}})
    assert not res["result"].get("isError") and alice.get("/api/city").json()["town"] == {ka: [30.0, 5.0]}
    bad = rpc(sb, "tools/call", {"name": "update_agent", "arguments": {"agent": "agent:999", "name": "x"}})
    assert bad["result"]["isError"]
    sb.post("/api/runtime/events", json={"events": [{"kind": "text", "data": {"text": "Moved Maya east."}},
                                                    {"kind": "done", "data": {"ok": True}}]})
    t = alice.get("/api/caretaker").json()["turns"][-1]
    assert (t["state"], t["reply"], t["changed"], t["can_undo"]) == ("done", "Moved Maya east.", True, True)
    alice.post(f"/api/caretaker/turns/{t['id']}/undo")
    assert alice.get("/api/city").json()["town"] == {}

    # the next message goes to the same sandbox: no new one to wake
    assert last(say(alice, "thanks"))["state"] == "working"
    assert len(boxes.started) == 1
    assert "pressed Undo" in sb.get(f"/api/runtime/inbox?after={msg['id']}").json()["messages"][0]["text"]


def test_a_sandbox_that_dies_fails_the_message(make_user, monkeypatch, boxes, client):
    alice = make_user("alice")
    with_key(alice, monkeypatch, OAT, "subscription")
    say(alice, "hello")
    [(run_id, token)] = boxes.started
    sb = sandbox_client(token)
    sb.post("/api/runtime/events", json={"events": [{"kind": "status", "data": {"status": "error", "detail": "boom"}}]})
    t = alice.get("/api/caretaker").json()["turns"][-1]
    assert t["state"] == "failed" and "boom" in t["reply"]
    assert last(say(alice, "again"))["state"] == "working" and len(boxes.started) == 2   # a fresh sandbox


def test_only_the_caretakers_sandbox_gets_its_tools(make_user, monkeypatch, boxes):
    alice, bob = make_user("alice"), make_user("bob")
    with_key(alice, monkeypatch, OAT, "subscription")
    with_key(bob, monkeypatch, OAT, "subscription")
    a = agent(alice, "maya")
    alice.post(f"/api/agents/{a['id']}/runs")                  # an agent's sandbox
    say(bob, "hi")                                             # bob's caretaker
    (_, agent_token), (_, bob_token) = boxes.started
    assert sandbox_client(agent_token).post("/api/runtime/caretaker", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 404
    # bob's caretaker can't reach alice's agent
    res = rpc(sandbox_client(bob_token), "tools/call", {"name": "update_agent", "arguments": {"agent": f"agent:{a['id']}", "name": "x"}})
    assert res["result"]["isError"] and alice.get(f"/api/agents/{a['id']}").json()["name"] == "maya"


def test_runner_runs_the_caretaker_without_file_tools(tmp_path, monkeypatch):
    import importlib
    import sys
    monkeypatch.setenv("AGENTTOWN_API_URL", "http://x")
    monkeypatch.setenv("AGENTTOWN_RUN_TOKEN", "rt_x")
    monkeypatch.syspath_prepend(str(__import__("pathlib").Path(__file__).parents[1] / "runner"))
    sys.modules.pop("runner", None)
    runner = importlib.import_module("runner")
    for k, v in {"HOME": tmp_path, "WORK": tmp_path, "emit": lambda *a, **k: None, "fresh_secrets": lambda: {}}.items():
        monkeypatch.setattr(runner, k, v)
    cmds = []
    monkeypatch.setattr(runner, "stream", lambda cmd, *a: (cmds.append(cmd), (0, ""))[1])
    m = {"kind": "caretaker", "agent": {"name": "The caretaker"}, "instructions": "You are the caretaker.", "team": [],
         "shared": [], "public": [], "tools": [{"connection_id": 0, "connection": "caretaker", "transport": "http",
                                                 "url": "http://x/api/runtime/caretaker", "hosted": True, "server": "caretaker",
                                                 "command": None, "usable": True, "all_tools": True, "tools": []}]}
    runner.Claude(m, {"kind": "subscription", "secret": OAT, "model": caretaker.MODEL, "thinking": "low"}, {}, []).turn("hi")
    [cmd] = cmds
    assert cmd[cmd.index("--system-prompt") + 1] == "You are the caretaker." and "--append-system-prompt" not in cmd
    assert "--tools=" in cmd and "--allowedTools=mcp__caretaker" in cmd


def test_the_caretaker_knows_empty_colonies(make_user, monkeypatch, claude):
    """It sees them in <town>, can rename, describe and delete one, and Undo puts them back."""
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Outreach", "about": ""}, {"name": "Home", "about": "bills"}]})
    fake = claude([("tool", "update_colony", {"colony": "outreach", "name": "Marketing", "about": "Posts"}),
                   ("tool", "update_colony", {"colony": "Home", "delete": True}),
                   ("tool", "update_colony", {"colony": "Nope", "name": "X"})], [("text", "Done.")])
    t = last(say(alice, "rename outreach to marketing and drop home"))
    town_block = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert '"empty_colonies"' in town_block and "Outreach" in town_block
    assert "which colony" in str(fake.calls[1]["messages"][-1]["content"])
    assert alice.get("/api/city").json()["empty_colonies"] == [{"name": "Marketing", "about": "Posts"}]
    alice.post(f"/api/caretaker/turns/{t['id']}/undo")
    assert alice.get("/api/city").json()["empty_colonies"] == [{"name": "Outreach", "about": ""}, {"name": "Home", "about": "bills"}]


def test_renaming_a_colony_through_the_caretaker_fills_the_empty_one(make_user, monkeypatch, claude):
    alice = make_user("alice")
    with_key(alice, monkeypatch)
    lead, x = agent(alice, "lead"), agent(alice, "xavi")
    alice.put(f"/api/agents/{lead['id']}/team", json={"member_ids": [x["id"]]})
    alice.put("/api/account/empty-colonies", json={"colonies": [{"name": "Studio", "about": "Makes videos"}]})
    claude([("tool", "update_colony", {"lead": f"agent:{lead['id']}", "name": "studio"})], [("text", "Done.")])
    t = last(say(alice, "call the lead's colony studio"))
    got = alice.get(f"/api/agents/{lead['id']}").json()
    assert (got["colony_name"], got["colony_about"]) == ("Studio", "Makes videos")
    assert alice.get("/api/city").json()["empty_colonies"] == []
    alice.post(f"/api/caretaker/turns/{t['id']}/undo")
    assert alice.get(f"/api/agents/{lead['id']}").json()["colony_name"] == ""
    assert alice.get("/api/city").json()["empty_colonies"] == [{"name": "Studio", "about": "Makes videos"}]
