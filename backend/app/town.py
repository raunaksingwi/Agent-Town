"""Agent Town's own tools for agents: see the person's town, and add agents and colonies to it.

Served by routers/hosted.py like Gmail and LinkedIn, on a hosted connection with app "town" (one per
person, made at sign-up and granted to their mayor, who builds agents with them: its agent-builder
skill). Looking is free. Adding always waits for the person's Add, as an approval event like an
email's Send (app/outbox.py): an agent's instructions are a prompt that runs with the person's apps,
so nothing an agent wrote becomes one without their yes. That holds whatever the run read, so prompt
injection can at most propose an agent they then turn down.

    list_agents     their agents: name, what each does, which colony it's in; and colonies named with no agents yet
    create_agent    a new agent (name, description, instructions), optionally into an existing colony
    create_colony   a team: a lead and its members, all agents they have by then, with a name and purpose.
                    Named like one of their empty colonies (User.empty_colonies), it fills that one in.
                    With no lead and no members, an empty colony: a named plot, its agents to come.
"""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import push
from .models import Agent, AgentToolGrant, McpConnection, Run, RunEvent, User

APP = "town"
APP_SLUG = "agent-town"         # how a market agent asks for these tools (`tools: agent-town`)
NAME = "Agent Town"
MAX_PENDING = 20               # proposals waiting at once from one chat: a runaway loop shouldn't bury them
MAX_INSTRUCTIONS = 50_000

TOOLS = {APP: [
    {"name": "list_agents", "description": "The person's agents in Agent Town: each one's name, what it does, and "
                                           "which colony (team) it's in; and empty_colonies, ones they named but "
                                           "haven't put agents in yet. Check this before proposing a new agent.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "create_agent", "description": "Propose a new agent for the person's town. Agent Town shows it to them "
                                            "with an Add button; it's only created if they press it, and you'll be told "
                                            "what they chose. Don't ask them in words as well.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "maxLength": 40, "description": "lowercase-with-hyphens, or a first name like 'maya'"},
         "description": {"type": "string", "maxLength": 200, "description": "one line: what it does and when to use it"},
         "instructions": {"type": "string", "maxLength": MAX_INSTRUCTIONS,
                          "description": "its instructions in markdown (its process, output format, what to ask before acting)"},
         "colony": {"type": "string", "maxLength": 60, "description": "optional: the name of an existing colony to join "
                    "(one with agents: to fill an empty colony, propose its agents, then create_colony with its name)"}},
         "required": ["name", "description", "instructions"]}},
    {"name": "create_colony", "description": "Propose a colony: a team whose lead hands work to its members. All of "
                                             "them must be agents the person has when they press Add (propose the "
                                             "agents first). An agent in another colony moves to this one. Use an "
                                             "empty colony's name to fill that colony in. Leave out lead and members "
                                             "for an empty colony: a named plot on the map whose agents come later.",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string", "maxLength": 60, "description": "e.g. Outreach, Product, Home"},
         "about": {"type": "string", "maxLength": 300, "description": "one line on what this colony is for"},
         "lead": {"type": "string", "description": "the agent the person talks to; leave out for an empty colony"},
         "members": {"type": "array", "items": {"type": "string"}, "maxItems": 20,
                     "description": "the agents it hands work to; none for a colony of one, just the lead"}},
         "required": ["name"]}},
]}


class TownError(ValueError):
    pass


def ensure_connection(db: Session, user: User) -> McpConnection:
    """Their "Agent Town" connection: the same one every time."""
    conn = db.scalar(select(McpConnection).where(McpConnection.owner_id == user.id, McpConnection.transport == "hosted",
                                                 McpConnection.app == APP))
    if conn is None:
        name = NAME if not db.scalar(select(McpConnection).where(McpConnection.owner_id == user.id,
                                                                 McpConnection.name == NAME)) else f"{NAME} (built in)"
        conn = McpConnection(owner_id=user.id, name=name, transport="hosted", app=APP, status="connected",
                             status_detail="Built in: lets an agent propose new agents and colonies",
                             server_name="Agent Town (hosted)")
        db.add(conn)
        from .google import sync_tools
        sync_tools(conn)
        db.flush()
    return conn


def grant(db: Session, user: User, agent: Agent) -> None:
    conn = ensure_connection(db, user)
    if not any(g.connection_id == conn.id for g in agent.grants):
        agent.grants.append(AgentToolGrant(connection_id=conn.id, tool_name=None))


def _agents(db: Session, owner_id: int) -> list[Agent]:
    return list(db.scalars(select(Agent).where(Agent.owner_id == owner_id).order_by(Agent.created_at)))


def _by_name(db: Session, owner_id: int, name: str) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.owner_id == owner_id, func.lower(Agent.name) == name.strip().lower()))


def leads(a: Agent) -> bool:
    """It leads a colony: it has a team, or it was given a colony's name (a colony of one, its team still to come).
    The same rule as the map's (frontend/src/colony.ts)."""
    return bool(a.team or a.colony_name)


def _colony_of(agents: list[Agent], a: Agent) -> str:
    """As the map groups them (frontend/src/colony.ts): a lead's own colony, or the first lead that has it."""
    if leads(a):
        return a.colony_name or f"{a.name}'s colony"
    lead = next((x for x in agents if a in x.team), None)
    return (lead.colony_name or f"{lead.name}'s colony") if lead else ""


def empty_colony(user: User, name: str) -> dict | None:
    """One of the colonies they named before putting agents in, by name (any case)."""
    return next((c for c in user.empty_colonies or [] if c["name"].lower() == name.strip().lower()), None)


def name_colony(user: User, lead: Agent, name: str, about: str | None = None) -> None:
    """Give a lead's colony its name, through whichever screen or tool: if they had named an empty colony
    the same (any case), that one is now this one, so it leaves the list and keeps its spelling and
    "what it's for" unless a new one is given. The one place this happens, so the map never shows a
    name twice."""
    name = " ".join(name.split())
    empty = empty_colony(user, name) if name else None
    if empty:
        user.empty_colonies = [c for c in user.empty_colonies if c is not empty]
    lead.colony_name = empty["name"] if empty else name
    if about is not None:
        lead.colony_about = " ".join(about.split())
    elif empty and empty.get("about") and not lead.colony_about:
        lead.colony_about = empty["about"]


def colony_taken_by(db: Session, user: User, name: str) -> Agent | None:
    """The lead whose colony already has this name (any case), if one does."""
    name = " ".join(name.split()).lower()
    return next((a for a in _agents(db, user.id) if a.colony_name.lower() == name), None) if name else None


def _text(args: dict, key: str, limit: int, required: bool = True) -> str:
    v = args.get(key)
    v = v.strip() if isinstance(v, str) else ""
    if key != "instructions":
        v = " ".join(v.split())                        # one line: it goes in the frontmatter
    if required and not v:
        raise TownError(f"{key} is required")
    if len(v) > limit:
        raise TownError(f"{key} is longer than {limit} characters")
    return v


MAX_EMPTY = 50                 # empty colonies one person may have (as on the Colonies screen)


def empty_colony_problem(db: Session, user: User, name: str) -> str:
    """Why there can't be an empty colony called that ("" if there can): no name twice on the map."""
    if (lead := colony_taken_by(db, user, name)) is not None:
        return f"{lead.name[0].upper()}{lead.name[1:]} already leads a colony called {lead.colony_name}"
    if empty_colony(user, name):
        return f"They already have an empty colony called {name}: put agents in it with create_colony and its name"
    if len(user.empty_colonies or []) >= MAX_EMPTY:
        return f"They have {MAX_EMPTY} empty colonies already"
    return ""


def proposal(db: Session, owner_id: int, name: str, args: dict) -> dict:
    """A create_agent / create_colony call, checked: what to show the person with an Add button."""
    if name == "create_agent":
        data = {"type": "agent", "name": _text(args, "name", 40), "description": _text(args, "description", 200),
                "instructions": _text(args, "instructions", MAX_INSTRUCTIONS), "colony": _text(args, "colony", 60, False)}
        if _by_name(db, owner_id, data["name"]):
            raise TownError(f"They already have an agent named {data['name']}: pick another name")
        if data["colony"] and empty_colony(db.get(User, owner_id), data["colony"]):
            raise TownError(f"{data['colony']} has no agents yet, so there's no lead to join: leave colony out, then "
                            "create_colony with that name once its lead and members are agents they have")
        return data
    if name == "create_colony":
        members = args.get("members", [])
        if not isinstance(members, list) or not all(isinstance(m, str) and m.strip() for m in members):
            raise TownError("members: a list of agent names")
        name, about = _text(args, "name", 60), _text(args, "about", 300, False)
        lead = _text(args, "lead", 80, False)   # no members (or only the lead): a colony of one
        if not lead:                            # no lead either: an empty colony, its agents to come
            if members:
                raise TownError("A colony with members needs a lead: say which agent the person talks to")
            if problem := empty_colony_problem(db, db.get(User, owner_id), name):
                raise TownError(problem)
            return {"type": "colony", "name": name, "about": about, "lead": "", "members": []}
        members = list(dict.fromkeys(m.strip() for m in members if m.strip().lower() != lead.lower()))[:20]
        return {"type": "colony", "name": name, "about": about, "lead": lead, "members": members}
    raise TownError(f"No tool {name}")


def call(db: Session, r: Run, name: str, args: dict) -> str:
    """A tool call from a run. Returns what to tell the agent; TownError for a bad call."""
    if name == "list_agents":
        agents = _agents(db, r.owner_id)
        return json.dumps({"agents": [{"name": a.name, "description": a.description, "colony": _colony_of(agents, a),
                                       "leads": [m.name for m in a.team]} for a in agents],
                           "empty_colonies": db.get(User, r.owner_id).empty_colonies or []}, ensure_ascii=False, indent=1)
    pending = db.scalar(select(func.count()).select_from(RunEvent).where(
        RunEvent.run_id == r.id, RunEvent.kind == "approval", RunEvent.data["state"].as_string() == "pending"))
    if pending >= MAX_PENDING:
        raise TownError(f"{MAX_PENDING} proposals are already waiting for the person: wait for their answers")
    data = proposal(db, r.owner_id, name, args)
    if data["type"] == "agent":
        title, body = f"{r.agent.name} wants to add an agent", f"{data['name']}: {data['description']}"
    else:
        title, body = f"{r.agent.name} wants to start a colony", f"{data['name']}: " + (
            (data['lead'] + (f" and {', '.join(data['members'])}" if data['members'] else ", on its own")) if data['lead']
            else "empty for now, its agents to come")
    db.add(RunEvent(run_id=r.id, kind="approval", data={**data, "state": "pending", "auto": False,
                                                        "why": "Adding to your town always needs your yes"}))
    db.commit()
    if not push.watched(r.id):
        push.notify(r.owner_id, title, body[:120], url="/chat?today", tag=f"town-{r.id}")
    return ("Not added yet: it's waiting for the person to press Add in Agent Town. Agent Town will tell you "
            "what they chose. Carry on with the next one if there's more to propose.")


def what(e: RunEvent) -> str:
    return f"the agent {e.data.get('name')}" if e.data.get("type") == "agent" else f"the colony {e.data.get('name')}"


def apply(db: Session, e: RunEvent) -> str:
    """They pressed Add on what an agent proposed: make it. "" when done, or what's wrong (it stays waiting)."""
    r = db.get(Run, e.run_id)
    err, agent_id = apply_proposal(db, db.get(User, r.owner_id), e.data)
    if not err:
        e.data = {**e.data, "state": "sent", "agent_id": agent_id}
    return err


def apply_proposal(db: Session, user: User, d: dict) -> tuple[str, int | None]:
    """Make a proposed agent or colony (the person pressed Add): ("", the agent or lead's id), or (what's wrong, None).
    Shared by agents' proposals and the caretaker's (app/caretaker.py)."""
    from .routers.agents import new_agent  # not at the top: the routers import this module
    if d["type"] == "agent":
        if _by_name(db, user.id, d["name"]):
            return f"You already have an agent named {d['name']}", None
        md = f"---\nname: {d['name']}\ndescription: {d['description']}\n---\n\n{d['instructions']}\n"
        a = new_agent(db, user, md, d["name"])
        db.flush()
        lead = next((x for x in _agents(db, user.id) if d.get("colony") and x.colony_name.lower() == d["colony"].lower()), None)
        if lead is not None:
            lead.team = [*lead.team, a]
        return "", a.id
    if not d["lead"]:                              # an empty colony: named now, filled in later
        if problem := empty_colony_problem(db, user, d["name"]):
            return problem, None
        user.empty_colonies = [*(user.empty_colonies or []), {"name": " ".join(d["name"].split()), "about": d.get("about") or ""}]
        return "", None
    lead = _by_name(db, user.id, d["lead"])
    members = [_by_name(db, user.id, n) for n in d["members"]]
    missing = [n for n, m in zip([d["lead"], *d["members"]], [lead, *members], strict=True) if m is None]
    if missing:
        return f"Add {', '.join(missing)} first: you don't have {'that agent' if len(missing) == 1 else 'those agents'} yet", None
    join_colony(db, user.id, lead, [m for m in members if m is not None])
    name_colony(user, lead, d["name"], d.get("about") or None)   # filling in one they named earlier takes its spelling
    return "", lead.id


def join_colony(db: Session, owner_id: int, lead: Agent, members: list[Agent]) -> None:
    """lead's team becomes members. One colony per agent: joining this one leaves the last, and a colony of
    one that joins another is no longer one (a lead with a team of its own keeps its colony, as on the map)."""
    members = [m for m in dict.fromkeys(members) if m.id != lead.id]
    for m in members:
        if not m.team:
            m.colony_name = m.colony_about = ""
    moving = {lead.id, *(m.id for m in members)}
    for other in _agents(db, owner_id):
        if other.id != lead.id and any(m.id in moving for m in other.team):
            other.team = [m for m in other.team if m.id not in moving]
    lead.team = members
