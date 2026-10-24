"""Agent Town API.  Run:  uv run uvicorn app.main:app --reload   (docs at /docs)"""

import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import mailindex, push, routines, views
from .auth import current_user
from .config import DEV_SECRET, settings
from .db import SessionLocal, get_db
from .models import Agent, McpConnection, PublicShare, Run, SharedFile, User
from .routers import account, agents, auth, caretaker, chat, connect, connect_linkedin, connect_mcp, files, guides, hosted, mcp, public, runs
from .routers import mail as mail_router
from .routers import routines as routines_router
from .routers.agents import owner_views, with_everything
from .routers.files import shared_view
from .routers.mcp import view as connection_view

log = logging.getLogger("agenttown")


def _local(url: str) -> bool:
    return urlparse(url).hostname in ("localhost", "127.0.0.1", "::1")


if settings().secret_key == DEV_SECRET:
    # The secret encrypts every stored key and token. With the public default anyone holding a copy
    # of the database can read them all, so only a laptop setup may run on it.
    if settings().sandbox_provider != "local" or not (_local(settings().public_url) and _local(settings().app_url)):
        raise RuntimeError("AGENTTOWN_SECRET_KEY is the dev default. Set a real one (python -c \"import secrets; "
                           "print(secrets.token_urlsafe(48))\") before running anywhere but on localhost.")
    log.warning("AGENTTOWN_SECRET_KEY is the dev default; set a real one before storing real credentials")

push._session = SessionLocal                     # notifications are sent from their own threads


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = routines.start_scheduler(SessionLocal) if settings().scheduler else None
    if stop:
        mailindex.start(SessionLocal, stop)      # its own thread: a first sync is slow, routines mustn't wait
    yield
    if stop:
        stop.set()


_docs = settings().api_docs
app = FastAPI(title="Agent Town", version="0.1.0", lifespan=lifespan,
              docs_url="/docs" if _docs else None, redoc_url="/redoc" if _docs else None,
              openapi_url="/openapi.json" if _docs else None)

# How much a request may carry. Imports bring whole folders of markdown; nothing else needs more
# than a couple of megabytes, and an unbounded body is an easy way to exhaust memory.
BODY_LIMIT, IMPORT_BODY_LIMIT = 2_000_000, 25_000_000


@app.middleware("http")
async def body_limit(request: Request, call_next):
    limit = IMPORT_BODY_LIMIT if request.url.path.startswith("/api/import/") else BODY_LIMIT
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > limit:
        return JSONResponse({"detail": f"That's more than one request takes ({limit // 1_000_000} MB)"}, status_code=413)
    if request.method in ("POST", "PUT", "PATCH") and not length and "chunked" in request.headers.get("transfer-encoding", ""):
        body = b""
        async for chunk in request.stream():
            body += chunk
            if len(body) > limit:
                return JSONResponse({"detail": f"That's more than one request takes ({limit // 1_000_000} MB)"}, status_code=413)
        request._body = body
    return await call_next(request)



@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    """CSRF guard. The session cookie is SameSite=Lax, so other sites can't send it on a POST.
    Belt and braces: a write whose Origin is another site is refused outright."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if origin and urlparse(origin).netloc != host:
            return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
    return await call_next(request)


for r in (auth.router, account.router, agents.router, mcp.router, public.router, runs.router, files.router, connect.router, connect_linkedin.router,
          connect_mcp.router, hosted.router, routines_router.router, chat.router, caretaker.router, caretaker.runtime, mail_router.router,
          guides.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/city", tags=["city"])
def city(user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    """Everything the map draws in one request: the public district for everyone,
    plus your private district and your tools when signed in."""
    shares = db.scalars(select(PublicShare).order_by(PublicShare.created_at)).all()
    out = {"me": views.user(user) if user else None, "public": [views.share(s) for s in shares],
           "agents": [], "connections": [], "shared_files": [], "town": {}, "map_style": "", "empty_colonies": []}
    if user:
        out["town"], out["map_style"], out["empty_colonies"] = user.town or {}, user.map_style, user.empty_colonies or []
        mine = db.scalars(with_everything(select(Agent).where(Agent.owner_id == user.id).order_by(Agent.created_at))).all()
        conns = db.scalars(select(McpConnection).where(McpConnection.owner_id == user.id)
                           .order_by(McpConnection.created_at)).all()
        live = dict(db.execute(select(Run.agent_id, Run.status).where(Run.owner_id == user.id, Run.ended_at.is_(None))).all())
        out["agents"] = [{**v, "run_status": live.get(a.id)} for a, v in zip(mine, owner_views(db, mine), strict=True)]
        out["connections"] = [connection_view(db, c) for c in conns]
        out["shared_files"] = [shared_view(f) for f in db.scalars(
            select(SharedFile).where(SharedFile.owner_id == user.id).order_by(SharedFile.path))]
    return out


# In production the built frontend (frontend/dist) is served from here, so it's one process.
mimetypes.add_type("application/manifest+json", ".webmanifest")   # the chat app's manifest
DIST = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(DIST, "assets")), name="assets")

    ROOT = os.path.realpath(DIST)

    # HEAD too: uptime monitors and link previews send it, and a plain @app.get answers 405
    @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def spa(path: str):
        # realpath, then check it's still inside dist: "%2e%2e/" in a URL arrives here as "../"
        candidate = os.path.realpath(os.path.join(ROOT, path))
        if path and candidate.startswith(ROOT + os.sep) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(ROOT, "index.html"))
