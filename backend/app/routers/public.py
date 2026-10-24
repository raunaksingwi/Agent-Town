from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import views
from ..auth import require_user
from ..db import get_db
from ..models import Agent, AgentFile, PublicShare, User
from ..schemas import ShareIn, SharePatch

router = APIRouter(prefix="/api/public", tags=["public district"])


def own_share(db: Session, user: User, share_id: int) -> PublicShare:
    s = db.get(PublicShare, share_id)
    if s is None or s.owner_id != user.id:
        raise HTTPException(404, "No such share")
    return s


@router.get("")
def list_shares(db: Session = Depends(get_db)):
    """The public district. Anyone, signed in or not, can see this."""
    return [views.share(s) for s in db.scalars(select(PublicShare).order_by(PublicShare.created_at))]


@router.get("/agents/{agent_id}")
def shared_agent(agent_id: int, db: Session = Depends(get_db)):
    """An agent someone shared, with its files, for anyone."""
    from .agents import public_agent
    return public_agent(db, agent_id)


@router.get("/{share_id}")
def get_share(share_id: int, db: Session = Depends(get_db)):
    s = db.get(PublicShare, share_id)
    if s is None:
        raise HTTPException(404, "No such share")
    return views.share(s, with_content=True)


@router.post("")
def share(body: ShareIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if body.kind == "agent":
        a = db.get(Agent, body.agent_id or 0)
        if a is None or a.owner_id != user.id:
            raise HTTPException(404, "No such agent")
        if db.scalar(select(PublicShare).where(PublicShare.kind == "agent", PublicShare.agent_id == a.id)):
            raise HTTPException(409, "Already shared")
        s = PublicShare(owner_id=user.id, kind="agent", agent_id=a.id, title=body.title or a.name)
    else:
        f = db.get(AgentFile, body.file_id or 0)
        if f is None or f.agent.owner_id != user.id:
            raise HTTPException(404, "No such file")
        if db.scalar(select(PublicShare).where(PublicShare.kind == "file", PublicShare.file_id == f.id)):
            raise HTTPException(409, "Already shared")
        s = PublicShare(owner_id=user.id, kind="file", file_id=f.id, title=body.title or f.path)
    s.note, s.allow_agent_use = body.note, body.allow_agent_use
    db.add(s)
    db.commit()
    return views.share(s)


@router.patch("/{share_id}")
def update_share(share_id: int, body: SharePatch, user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = own_share(db, user, share_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(s, field, value)
    db.commit()
    return views.share(s)


@router.delete("/{share_id}")
def unshare(share_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    db.delete(own_share(db, user, share_id))
    db.commit()
    return {"ok": True}
