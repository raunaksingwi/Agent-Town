"""Turn whatever someone drops in (a folder like ~/.claude, a repo of agents, or a few .md files)
into agents and shared files, so nobody has to know how agents are put together.

  agent    a markdown file whose frontmatter has `name:` (the Claude Code / Cursor agent format),
           unless it's a skill (SKILL.md, skills/), a slash command (commands/) or a memory note
           (memory/, or frontmatter with `metadata:` / `type:`, which agent files don't have)
  floors   the files an agent's instructions point at, by markdown link or `path`, and what
           those point at in turn: that agent's own knowledge
  shared   a file several agents point at, or that none does: every agent can read it, and it's
           stored once instead of copied
  skipped  hidden folders, and paths we can't store

  command  a slash command with the same name as an agent (commands/lead.md next to
           agents/lead.md): the person picks which one is the agent's instructions. By default the
           command, when the agent file is only a guard ("do not use…") or is much shorter.
  team     an agent whose instructions talk about handing work off (launch, delegate, route…)
           and name other agents being imported gets them as its team (never a self-declared leaf)

No agent definition at all (a folder of notes, or one plain .md)? Then one file is "the agent":
the only file if there's one, otherwise the one the person picks (`main`), and everything else
becomes its floors.
"""

import posixpath
import re

from .views import frontmatter

TEXT = (".md", ".markdown", ".txt")
DEPTH = 2  # follow links from an agent, and from what it links to; not the whole web of files
LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")
TICKED = re.compile(r"`([^`\s]+\.(?:md|markdown|txt))`")
NOT_AGENT_DIRS = {"skills", "commands", "memory", "memories"}
GUARD = re.compile(r"do not use|don't use|not (?:be )?used as|accidental", re.I)
DELEGATES = re.compile(r"\b(task-launch|launch|delegat|dispatch|spawn|route|hand (?:it )?off|fan[- ]out)", re.I)
# "Leaf." / "You are a leaf" / "(leaf)" / "Do not spawn": a leaf saying so about itself, not a lead talking about leaves
LEAF = re.compile(r"\bLeaf\b|[Yy]ou are a \**leaf|\(leaf\)|[Dd]o not spawn|[Dd]on't spawn|[Dd]oes not spawn|[Nn]ever spawn")


def strip_root(paths: list[str]) -> dict[str, str]:
    """A dropped folder arrives as my-agents/content/x.md; the my-agents/ part means nothing to the agent."""
    norm = {p: posixpath.normpath(p.replace("\\", "/").lstrip("/")) for p in paths}
    firsts = {n.split("/")[0] for n in norm.values()}
    if len(firsts) == 1 and all("/" in n for n in norm.values()):
        root = firsts.pop() + "/"
        norm = {p: n[len(root):] for p, n in norm.items()}
    return norm


def storable(path: str) -> str | None:
    """The path a file is stored and written at, or None if we won't keep it (hidden folders)."""
    parts = [s for s in path.split("/") if s not in ("", ".")]
    if not parts or any(s.startswith(".") or s == ".." for s in parts):
        return None
    parts = [re.sub(r"[^A-Za-z0-9_. -]+", "-", s).strip(" -") or "file" for s in parts]
    out = "/".join(parts)
    if out.endswith(".markdown"):
        out = out[:-len(".markdown")] + ".md"
    if not out.endswith((".md", ".txt")) or len(out) > 200 or not re.match(r"[A-Za-z0-9_]", out):
        return None
    return out


def is_agent(path: str, text: str) -> bool:
    parts = path.split("/")
    if parts[-1] == "SKILL.md" or NOT_AGENT_DIRS & set(parts[:-1]):
        return False
    meta, _ = frontmatter(text)
    return bool(meta.get("name")) and "metadata" not in meta and "type" not in meta


def stem(path: str) -> str:
    return posixpath.splitext(posixpath.basename(path))[0]


def describe(text: str) -> str:
    """One line on what it does: its frontmatter description, or its title without "/name —"."""
    meta, body = frontmatter(text)
    if meta.get("description"):
        return meta["description"][:300]
    for line in body.splitlines():
        line = line.strip()
        if line:
            return re.sub(r"^#+\s*(/\S+\s*[—–-]\s*)?", "", line)[:300]
    return ""


def references(text: str) -> list[str]:
    out = []
    for ref in LINK.findall(text) + TICKED.findall(text):
        ref = ref.split("#")[0]
        if ref and not re.match(r"[a-z]+:", ref):  # not http:, mailto:, …
            out.append(ref)
    return out


def resolve(ref: str, source: str, known: set[str]) -> str | None:
    """`../../content/a.md` from .claude/agents/x.md, `content/a.md` from anywhere, or a unique
    file name: whichever matches a file that was actually uploaded."""
    for cand in (posixpath.normpath(posixpath.join(posixpath.dirname(source), ref)),
                 posixpath.normpath(ref.lstrip("/"))):
        if cand in known:
            return cand
    tail = posixpath.normpath(ref).lstrip("./")
    hits = [k for k in known if k == tail or k.endswith("/" + tail)]
    return hits[0] if len(hits) == 1 else None


def plan(files: dict[str, str], main: str | None = None, choices: dict[str, str] | None = None) -> dict:
    """files: uploaded path -> text. Returns what an import would create; nothing is written.
    choices: agent name -> the source to use for it, when it has a command as well as an agent file."""
    up = strip_root(list(files))
    texts = {up[p]: files[p] for p in files}
    skipped, store = [], {}
    taken: dict[str, str] = {}
    for p in sorted(texts):
        s = storable(p)
        if s is not None and s in taken:
            skipped.append({"path": p, "reason": f"same name as {taken[s]}"})
            continue
        if s is not None:
            taken[s] = p
        store[p] = s

    if main is not None:
        main = up.get(main, main)
    agents = [p for p in sorted(texts) if is_agent(p, texts[p])] if main is None else [main]
    if not agents and len(texts) == 1:
        agents = list(texts)

    # an agent file and a slash command with the same name: which one is the agent?
    commands = {stem(p): p for p in texts if "commands" in p.split("/")[:-1]}
    alternatives: dict[str, list[dict]] = {}
    chosen = []
    for a in agents:
        name = (frontmatter(texts[a])[0].get("name") or stem(a)).strip()
        cmd = commands.get(name) if main is None else None
        if not cmd:
            chosen.append(a)
            continue
        guard = bool(GUARD.search(frontmatter(texts[a])[0].get("description", "")))
        longer = texts[cmd].count("\n") > 1.5 * texts[a].count("\n")
        pick = (choices or {}).get(name) or (cmd if guard or longer else a)
        alternatives[name] = [{"source": a, "kind": "agent", "lines": texts[a].count("\n") + 1},
                              {"source": cmd, "kind": "command", "lines": texts[cmd].count("\n") + 1}]
        chosen.append(pick if pick in (a, cmd) else a)
    skip = {alt["source"] for alts in alternatives.values() for alt in alts} - set(chosen)
    named = {c: (frontmatter(texts[c])[0].get("name") or stem(c)).strip() for c in chosen}
    agents = chosen
    if not agents:
        return {"agents": [], "shared": [], "skipped": skipped, "needs_main": True,
                "candidates": [p for p in sorted(texts) if store.get(p)]}

    knowledge = {p for p in texts if p not in agents and p not in skip and store.get(p)}
    linked: dict[str, set[str]] = {}
    for a in agents:
        seen, frontier = set(), [a]
        for _ in range(DEPTH):
            nxt = []
            for src in frontier:
                for ref in references(texts[src]):
                    hit = resolve(ref, src, knowledge)
                    if hit and hit not in seen:
                        seen.add(hit)
                        nxt.append(hit)
            frontier = nxt
        linked[a] = seen if main is None else set(knowledge)  # one agent: everything is its own
    users = {k: sum(k in linked[a] for a in agents) for k in knowledge}

    out_agents = []
    for a in agents:
        name = named[a][:80]
        own = sorted(k for k in linked[a] if users[k] == 1)
        team = []
        if DELEGATES.search(texts[a]) and not LEAF.search(texts[a]):     # a leaf hands nothing off
            team = [named[o] for o in agents if o != a and re.search(rf"(?<![\w-]){re.escape(named[o])}(?![\w-])", texts[a], re.I)]
        out_agents.append({"source": a, "name": name, "description": describe(texts[a]),
                           "files": [{"source": k, "path": store[k]} for k in own],
                           "alternatives": alternatives.get(name, []), "team": team})
    shared = sorted(k for k in knowledge if users[k] != 1)
    for p in sorted(texts):
        if p in skip:
            skipped.append({"path": p, "reason": "the other choice for its agent"})
        elif store.get(p) is None and p not in agents and not any(s["path"] == p for s in skipped):
            skipped.append({"path": p, "reason": "hidden folder" if "/." in "/" + p else "unusable path"})
    return {"agents": out_agents, "shared": [{"source": k, "path": store[k]} for k in shared],
            "skipped": skipped, "needs_main": False, "candidates": []}
