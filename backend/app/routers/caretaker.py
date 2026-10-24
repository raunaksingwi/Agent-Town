"""The caretaker's chat (app/caretaker.py): one conversation per person, a turn per message. And, for
its sandbox on a subscription, its tools over MCP (/api/runtime/caretaker, with the run's token)."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session, sessionmaker

from .. import caretaker
from ..auth import require_user
from ..db import get_db
from ..models import CaretakerTurn, Run, User
from ..runs import launch
from ..schemas import Coord
from ..timeutil import iso
from .runs import current_run

router = APIRouter(prefix="/api/caretaker", tags=["caretaker"])

MapKey = Annotated[str, StringConstraints(pattern=r"^((agent|station|shared):\d{1,12}|files|library|square|colony:[a-z0-9-]{1,40})$")]
AreaKey = Annotated[str, StringConstraints(pattern=r"^(square|colony:[a-z0-9-]{1,40})$")]


class Building(BaseModel):
    """One building or area as the browser drew it: top-left corner and size, in tiles from the square.
    A building says which area it's in; an area (kind "area": a colony's block, or the square) has the
    corner its buildings' saved spots count from, and its room (x, y, w, h): where they may stand."""
    key: MapKey
    kind: str = Field(default="", max_length=20)
    label: str = Field(default="", max_length=120)
    x: Coord
    y: Coord
    w: float = Field(ge=0, le=200)
    h: float = Field(ge=0, le=200)
    area: AreaKey | None = None
    corner: tuple[Coord, Coord] | None = None
    room: tuple[Coord, Coord, Annotated[float, Field(ge=0, le=200)], Annotated[float, Field(ge=0, le=200)]] | None = None


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    layout: list[Building] = Field(default_factory=list, max_length=1000)
    theme: str = Field(default="", max_length=20)


class DecisionIn(BaseModel):
    add: bool


def own_turn(db: Session, user: User, turn_id: int) -> CaretakerTurn:
    t = db.get(CaretakerTurn, turn_id)
    if t is None or t.owner_id != user.id:
        raise HTTPException(404, "No such message")
    return t


def turn_view(t: CaretakerTurn, can_undo: bool) -> dict:
    # proposals look like an agent's approval events, so the app draws them with the same card
    return {"id": t.id, "text": t.text, "reply": t.reply, "actions": t.actions, "created_at": iso(t.created_at),
            "state": t.state, "changed": t.undo is not None, "undone": t.undone, "can_undo": can_undo and t.state != "working",
            "proposals": [{"id": i, "kind": "approval", "created_at": iso(t.created_at),
                           "data": {k: v for k, v in p.items() if k != "told"}} for i, p in enumerate(t.proposals)]}


def _views(ts: list[CaretakerTurn]) -> list[dict]:
    """Undo goes newest first: only the latest change still in place can be undone."""
    last = next((t.id for t in reversed(ts) if t.undo is not None and not t.undone), None)
    return [turn_view(t, t.id == last) for t in ts]


def _conversation(db: Session, user: User) -> list[dict]:
    return _views(caretaker.turns(db, user, caretaker.conversation_of(db, user))[-50:])


@router.get("")
def get_caretaker(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Its conversation, and whether it can think. While it works in its sandbox, the app polls this."""
    caretaker.check(db, user)
    try:
        cred, _ = caretaker.credential(db, user)
        ready, why, via = True, "", cred.kind
    except caretaker.NeedsKey as e:
        ready, why, via = False, str(e), ""
    return {"ready": ready, "why": why, "via": via, "model": caretaker.MODEL, "turns": _conversation(db, user)}


@router.post("/messages")
def send(body: MessageIn, bg: BackgroundTasks, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Not async: on an API key it waits on the model, and FastAPI runs plain functions in a worker thread.
    On a subscription it answers at once with the turn "working"; a new sandbox starts after the response."""
    layout = {b.key: b.model_dump() for b in body.layout}
    try:
        turn, token = caretaker.ask(db, user, body.text.strip(), layout, body.theme)
    except caretaker.NeedsKey as e:
        raise HTTPException(409, str(e))
    except caretaker.Busy as e:                     # 429, not 409: the app reads 409 as "connect your Claude"
        raise HTTPException(429, str(e))
    except caretaker.CaretakerError as e:
        raise HTTPException(502, str(e))
    if token:
        bg.add_task(launch, sessionmaker(bind=db.get_bind(), expire_on_commit=False), turn.run_id, token)
    return {"turns": _conversation(db, user)}


@router.post("/turns/{turn_id}/undo")
def undo(turn_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    err = caretaker.undo(db, user, own_turn(db, user, turn_id))
    if err:
        raise HTTPException(409, err)
    return {"turns": _conversation(db, user)}


@router.post("/turns/{turn_id}/proposals/{index}")
def decide(turn_id: int, index: int, body: DecisionIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    t = own_turn(db, user, turn_id)
    if not 0 <= index < len(t.proposals):
        raise HTTPException(404, "No such proposal")
    err = caretaker.decide(db, user, t, index, body.add)
    if err:
        raise HTTPException(409, err)
    return {"turns": _conversation(db, user)}


@router.post("/start-over")
def start_over(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """A fresh conversation. The old turns stay on record, just not shown or sent to the model."""
    if caretaker.turns(db, user, caretaker.conversation_of(db, user)):
        user.caretaker_conversation = caretaker.conversation_of(db, user) + 1
        db.commit()
    return {"turns": []}


# ---- its sandbox's tools (subscription only) ---------------------------------------------

def _reply(mid, result=None, error: tuple[int, str] | None = None) -> JSONResponse:
    body = {"jsonrpc": "2.0", "id": mid}
    body.update({"error": {"code": error[0], "message": error[1]}} if error else {"result": result})
    return JSONResponse(body)


runtime = APIRouter(tags=["runtime"])


@runtime.post("/api/runtime/caretaker", include_in_schema=False)
def runtime_tools(msg: dict = Body(...), r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """The caretaker's tools over MCP, for its own sandbox only: an agent's run token gets a 404."""
    if r.kind != "caretaker":
        return JSONResponse({"error": "Not a caretaker run"}, status_code=404)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return Response(status_code=202)
    if method == "initialize":
        return _reply(mid, {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                            "capabilities": {"tools": {}}, "serverInfo": {"name": "agent-town-caretaker", "version": "1.0"}})
    if method == "tools/list":
        return _reply(mid, {"tools": [{"name": d["name"], "description": d["description"], "inputSchema": d["input_schema"]}
                                      for d in caretaker.TOOL_DEFS]})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            text = caretaker.call_tool(db, r, str(p.get("name", "")), dict(p.get("arguments") or {}))
            return _reply(mid, {"content": [{"type": "text", "text": text}]})
        except caretaker.ToolError as e:
            return _reply(mid, {"isError": True, "content": [{"type": "text", "text": str(e)}]})
    if method == "ping":
        return _reply(mid, {})
    return _reply(mid, error=(-32601, f"No method {method}"))
