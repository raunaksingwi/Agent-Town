"""Importing a folder of agents. The folder here is made up, shaped like a typical agents repo:
Claude Code agents under .claude/agents/ that link to shared knowledge elsewhere in the tree."""

from app import importer

AGENT = "---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n\n{body}\n"

FOLDER = {
    "team/README.md": "# Our agents\n\nSee [the writer](.claude/agents/writer.md).\n",
    "team/.claude/agents/writer.md": AGENT.format(
        name="writer", desc="Writes posts.",
        body="Before writing, read [about us](../../content/about.md) and "
             "[the playbook](../../content/writing-playbook.md)."),
    "team/.claude/agents/editor.md": AGENT.format(
        name="editor", desc="Edits posts.", body="Read `content/about.md` first."),
    "team/.claude/skills/tidy/SKILL.md": "---\nname: tidy\ndescription: a skill\n---\nTidy up.\n",
    "team/commands/go.md": "---\nname: go\n---\nA slash command.\n",
    "team/content/about.md": "We make a travel app.\n",
    "team/content/writing-playbook.md": "Hooks first. See [examples](examples/hooks.md).\n",
    "team/content/examples/hooks.md": "1. Wait, you can do that?\n",
    "team/notes/ideas.txt": "ideas nobody links to\n",
    "team/memory/likes-short-posts.md": "---\nname: likes-short-posts\nmetadata:\n  type: feedback\n---\nKeep it short.\n",
    "team/notes/user.md": "---\nname: user-role\ntype: user\n---\nA founder.\n",
    "team/.cursor/rules.md": "hidden\n",
}


def test_plan_finds_agents_their_files_and_what_is_shared():
    p = importer.plan(FOLDER)
    assert not p["needs_main"]
    agents = {a["name"]: a for a in p["agents"]}
    assert set(agents) == {"writer", "editor"}  # not the skill, the command, or memory notes
    assert agents["writer"]["description"] == "Writes posts."
    # the writer's own: its playbook, and what the playbook links to (two levels)
    assert [f["path"] for f in agents["writer"]["files"]] == ["content/examples/hooks.md", "content/writing-playbook.md"]
    assert agents["editor"]["files"] == []
    shared = [f["path"] for f in p["shared"]]
    assert "content/about.md" in shared          # both agents read it: stored once
    assert "notes/ideas.txt" in shared           # nobody links it: every agent may read it
    assert "commands/go.md" in shared
    assert all(not s.startswith(".") for s in shared)
    assert {s["path"] for s in p["skipped"]} >= {".cursor/rules.md", ".claude/skills/tidy/SKILL.md"}


def test_one_plain_file_is_an_agent():
    p = importer.plan({"notes/helper.md": "# Helper\n\nBe helpful.\n"})
    assert [a["name"] for a in p["agents"]] == ["helper"]


def test_folder_without_definitions_asks_which_file_is_the_agent():
    files = {"me/plan.md": "# Do this\nRead [style](style.md).\n", "me/style.md": "short\n", "me/extra.md": "x\n"}
    p = importer.plan(files)
    assert p["needs_main"] and p["candidates"] == ["extra.md", "plan.md", "style.md"]
    p = importer.plan(files, main="plan.md")
    [a] = p["agents"]
    assert a["name"] == "plan" and [f["path"] for f in a["files"]] == ["extra.md", "style.md"] and p["shared"] == []


def test_storable_paths():
    assert importer.storable("content/a b&c.markdown") == "content/a b-c.md"
    assert importer.storable(".claude/x.md") is None
    assert importer.storable("notes/x.png") is None


def upload(files):
    return [{"path": k, "content": v} for k, v in files.items()]


def test_import_creates_agents_and_shared_files(make_user):
    alice = make_user("alice")
    p = alice.post("/api/import/preview", json={"files": upload(FOLDER)}).json()
    assert {a["name"]: a["exists"] for a in p["agents"]} == {"writer": False, "editor": False}
    body = {"files": upload(FOLDER),
            "agents": [{"source": a["source"], "name": a["name"], "files": [f["source"] for f in a["files"]]}
                       for a in p["agents"]],
            "shared": [s["source"] for s in p["shared"]]}
    r = alice.post("/api/import", json=body).json()
    assert sorted(a["name"] for a in r["created"]) == ["editor", "writer"] and r["shared"] == len(p["shared"])
    writer = next(a for a in r["created"] if a["name"] == "writer")
    assert [f["path"] for f in writer["files"]] == ["AGENT.md", "content/examples/hooks.md", "content/writing-playbook.md"]
    assert writer["description"] == "Writes posts."

    city = alice.get("/api/city").json()
    assert "content/about.md" in [f["path"] for f in city["shared_files"]]

    # every agent's manifest carries the shared files
    m = alice.get(f"/api/agents/{writer['id']}/manifest").json()
    assert "content/about.md" in [f["path"] for f in m["shared"]]

    # importing again updates by name instead of making copies
    p2 = alice.post("/api/import/preview", json={"files": upload(FOLDER)}).json()
    assert all(a["exists"] for a in p2["agents"])
    r2 = alice.post("/api/import", json=body).json()
    assert r2["created"] == [] and len(r2["updated"]) == 2
    assert len(alice.get("/api/agents").json()) == 2


def test_shared_files_are_private(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    f = alice.put("/api/files", json={"path": "about.md", "content": "secret plans\n"}).json()
    assert bob.get(f"/api/files/{f['id']}").status_code == 404
    assert bob.delete(f"/api/files/{f['id']}").status_code == 404
    assert bob.get("/api/files").json() == []
    assert bob.get("/api/city").json()["shared_files"] == []
    a = bob.post("/api/agents", json={"markdown": AGENT.format(name="b", desc="", body="hi")}).json()
    assert bob.get(f"/api/agents/{a['id']}/manifest").json()["shared"] == []
    assert alice.get(f"/api/files/{f['id']}").json()["content"] == "secret plans\n"
    assert alice.delete(f"/api/files/{f['id']}").json() == {"ok": True}


def test_import_rejects_unknown_sources(make_user):
    alice = make_user("alice")
    r = alice.post("/api/import", json={"files": upload({"a.md": "x"}), "agents": [{"source": "nope.md", "name": "n"}]})
    assert r.status_code == 422


TEAM_FOLDER = {
    "crew/agents/boss.md": "---\nname: boss\ndescription: Do not use as an orchestrator here.\n---\nGuard: go to the main thread.\n",
    "crew/commands/boss.md": "# /boss — run the crew\n\nYou lead. Read `notes/priorities.md`.\n\n"
                             "Route each job: launch scout for research and scribe for writing.\n" + "More detail.\n" * 10,
    "crew/agents/scout.md": "---\nname: scout\ndescription: Finds things. Leaf.\n---\nLeaf. Do not spawn subagents. Report to boss.\n",
    "crew/agents/scribe.md": "---\nname: scribe\ndescription: Writes things.\n---\nYou are a leaf: write, then return. Boss reads it.\n",
    "crew/commands/sync.md": "# /sync — back up and pull\n",
    "crew/notes/priorities.md": "1. Ship.\n",
}


def test_command_beats_a_guard_and_suggests_a_team():
    p = importer.plan(TEAM_FOLDER)
    agents = {a["name"]: a for a in p["agents"]}
    assert set(agents) == {"boss", "scout", "scribe"}               # /sync is a command, not an agent
    boss = agents["boss"]
    assert boss["source"] == "commands/boss.md"                     # the guard file loses
    assert [x["kind"] for x in boss["alternatives"]] == ["agent", "command"]
    assert boss["description"] == "run the crew"
    assert [f["path"] for f in boss["files"]] == ["notes/priorities.md"]
    assert sorted(boss["team"]) == ["scout", "scribe"]
    assert agents["scout"]["team"] == [] and agents["scribe"]["team"] == []   # leaves name the boss but lead nobody
    assert "agents/boss.md" in {s["path"] for s in p["skipped"]}

    # the person can pick the agent file instead
    p2 = importer.plan(TEAM_FOLDER, choices={"boss": "agents/boss.md"})
    assert next(a for a in p2["agents"] if a["name"] == "boss")["source"] == "agents/boss.md"


def test_import_sets_the_team_and_the_run_gets_it(make_user):
    alice = make_user("alice")
    p = alice.post("/api/import/preview", json={"files": upload(TEAM_FOLDER)}).json()
    body = {"files": upload(TEAM_FOLDER), "shared": [s["source"] for s in p["shared"]],
            "agents": [{"source": a["source"], "name": a["name"], "files": [f["source"] for f in a["files"]], "team": a["team"]}
                       for a in p["agents"]]}
    r = alice.post("/api/import", json=body).json()
    boss = next(a for a in r["created"] if a["name"] == "boss")
    assert boss["description"] == "run the crew"
    names = {a["id"]: a["name"] for a in r["created"]}
    assert sorted(names[i] for i in boss["team"]) == ["scout", "scribe"]
    m = alice.get(f"/api/agents/{boss['id']}/manifest").json()
    assert sorted(t["slug"] for t in m["team"]) == ["scout", "scribe"]
    assert m["instructions"].startswith("# /boss")
    scout = next(t for t in m["team"] if t["slug"] == "scout")
    assert scout["instructions"].startswith("Leaf.") and scout["files"] == []


def test_team_is_your_own_agents_only(make_user):
    alice, bob = make_user("alice"), make_user("bob")
    a = alice.post("/api/agents", json={"markdown": AGENT.format(name="lead", desc="", body="x")}).json()
    b = alice.post("/api/agents", json={"markdown": AGENT.format(name="helper", desc="", body="x")}).json()
    theirs = bob.post("/api/agents", json={"markdown": AGENT.format(name="spy", desc="", body="x")}).json()
    assert alice.put(f"/api/agents/{a['id']}/team", json={"member_ids": [theirs["id"]]}).status_code == 404
    assert alice.put(f"/api/agents/{a['id']}/team", json={"member_ids": [a["id"]]}).status_code == 422
    assert bob.put(f"/api/agents/{a['id']}/team", json={"member_ids": []}).status_code == 404
    assert alice.put(f"/api/agents/{a['id']}/team", json={"member_ids": [b["id"], b["id"]]}).json()["team"] == [b["id"]]
    alice.delete(f"/api/agents/{b['id']}")                          # deleting a member takes it off the team
    assert alice.get(f"/api/agents/{a['id']}").json()["team"] == []
