"""The agent market: ready-made agents anyone can add to their town, read from agents/ at the
repo root (one folder per agent, added by pull request; see agents/README.md).

    agents/<slug>/AGENT.md     the agent; its frontmatter says what the market shows
    agents/<slug>/*.md|*.txt   what it knows (optional, any sub-folders)

Frontmatter keys: name, description, tags, author (required); color, building, tools (apps it works
best with), team (other market agents it hands work to), colony and about (a lead's colony: its name
and what it's for), ask (questions for "Make it your own", separated by |), all optional.
"""

import re
from functools import lru_cache
from pathlib import Path

from .schemas import file_path_problem
from .views import frontmatter

ROOT = Path(__file__).resolve().parents[2] / "agents"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
MAX_FILE = 200_000
REQUIRED = ("name", "description", "tags", "author")


def _list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def load_one(folder: Path) -> dict:
    files = []
    for f in sorted(folder.rglob("*")):
        if f.is_file() and f.suffix in (".md", ".txt"):
            files.append({"path": f.relative_to(folder).as_posix(), "content": f.read_text()})
    definition = next((f for f in files if f["path"] == "AGENT.md"), None)
    meta = frontmatter(definition["content"])[0] if definition else {}
    return {
        "slug": folder.name, "name": meta.get("name", ""), "description": meta.get("description", ""),
        "tags": _list(meta.get("tags", "")), "author": meta.get("author", ""), "color": meta.get("color", ""),
        "building": meta.get("building", ""), "tools": _list(meta.get("tools", "")), "team": _list(meta.get("team", "")),
        "colony": meta.get("colony", ""), "about": meta.get("about", ""),
        "ask": [q.strip() for q in meta.get("ask", "").split("|") if q.strip()],
        "files": files, "meta": meta,
    }


@lru_cache
def catalog() -> dict[str, dict]:
    """Every market agent by slug. Read once: the folder only changes with a deploy."""
    if not ROOT.is_dir():
        return {}
    return {d.name: load_one(d) for d in sorted(ROOT.iterdir()) if d.is_dir() and SLUG.match(d.name)}


def problems(entry: dict, names: set[str]) -> list[str]:
    """What's wrong with a market agent, for the contribution checks (tests/test_marketplace.py)."""
    out = []
    if not any(f["path"] == "AGENT.md" for f in entry["files"]):
        out.append("no AGENT.md")
    for key in REQUIRED:
        if not entry["meta"].get(key):
            out.append(f"AGENT.md frontmatter needs `{key}:`")
    if entry["color"] and not re.fullmatch(r"#[0-9a-fA-F]{6}", entry["color"]):
        out.append("color must look like #3f8fd2")
    if entry["building"] and entry["building"] not in ("studio", "office", "forge", "library", "lab", "observatory", "tavern", "cottage", "tower"):
        out.append(f"unknown building {entry['building']!r}")
    for m in entry["team"]:
        if m not in names:
            out.append(f"team member {m!r} isn't a market agent")
    if (entry["colony"] or entry["about"]) and not entry["team"]:
        out.append("colony and about are for a lead: add `team:`")
    if len(entry["colony"]) > 60 or len(entry["about"]) > 300:
        out.append("colony: up to 60 characters; about: up to 300")
    if len(entry["ask"]) > 5 or any(len(q) > 200 for q in entry["ask"]):
        out.append("ask: at most 5 questions, each under 200 characters")
    if len(entry["files"]) > 50:
        out.append("more than 50 files")
    for f in entry["files"]:
        if file_path_problem(f["path"]):
            out.append(f"file path not allowed: {f['path']}")
        if len(f["content"]) > MAX_FILE:
            out.append(f"{f['path']} is over {MAX_FILE} characters")
    return out
