"""Guides anyone can read, people or their agents (no sign-in: they hold nothing of anyone's).

Each one is a markdown file that also ships with an agent: the mayor reads create-an-agent.md from its
agent-builder skill, and this serves the same file, so the two never drift apart.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from ..marketplace import ROOT

router = APIRouter(prefix="/api/guides", tags=["guides"])

GUIDES = {
    "create-an-agent": ("Create an agent in Agent Town", ROOT / "mayor" / "skills" / "agent-builder" / "create-an-agent.md"),
}


# HEAD too, for link previews and uptime checks (as the pages are)
@router.api_route("", methods=["GET", "HEAD"])
def list_guides():
    return [{"name": name, "title": title, "url": f"/api/guides/{name}"} for name, (title, _) in GUIDES.items()]


@router.api_route("/{name}", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def guide(name: str):
    """The guide as markdown. `create-an-agent.md` works as well as `create-an-agent`."""
    entry = GUIDES.get(name.removesuffix(".md"))
    if entry is None:
        raise HTTPException(404, "No such guide")
    return PlainTextResponse(entry[1].read_text(), media_type="text/markdown; charset=utf-8")
