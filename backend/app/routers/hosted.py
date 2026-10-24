"""Tools Agent Town hosts itself (Gmail, Calendar, LinkedIn, its own town tools, read-only web APIs), served over MCP to a run's sandbox.

    POST /api/runtime/mcp/{connection_id}     JSON-RPC: initialize, tools/list, tools/call
    POST /api/runtime/mail                    the same, for mail between colonies (app/mail.py): no
                                              connection, every front door and the mayor get it

The sandbox authenticates with its run token, like the rest of /api/runtime. A run may only use a
connection its agent (or a teammate) was granted, and only the tools granted; then the call is made
here with the owner's Google or LinkedIn token or the API's stored header, which never leave this server.
"""

import httpx
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from .. import google, linkedin, mail, mailindex, mcp_client, outbox, town, webapi
from ..db import get_db
from ..models import McpConnection, OAuthAccount, Run
from .runs import current_run

router = APIRouter(tags=["runtime"])


def allowed_tools(r: Run, conn_id: int) -> set[str] | None:
    """The tool names this run may call on that connection: None means all of them, an empty set none."""
    names: set[str] = set()
    if r.agent is None:                               # the caretaker's run: its tools are elsewhere (routers/caretaker.py)
        return names
    for agent in [r.agent, *r.agent.team]:
        for g in agent.grants:
            if g.connection_id == conn_id:
                if g.tool_name is None:
                    return None
                names.add(g.tool_name)
    return names


def _reply(mid, result=None, error: tuple[int, str] | None = None) -> JSONResponse:
    body = {"jsonrpc": "2.0", "id": mid}
    body.update({"error": {"code": error[0], "message": error[1]}} if error else {"result": result})
    return JSONResponse(body)


@router.post("/api/runtime/mcp/{connection_id}")
def mcp(connection_id: int, msg: dict = Body(...), r: Run = Depends(current_run), db: Session = Depends(get_db)):
    """Not async: tool calls wait on Google, and FastAPI runs plain functions in a worker thread."""
    conn = db.get(McpConnection, connection_id)
    allowed = allowed_tools(r, connection_id) if conn and conn.owner_id == r.owner_id else set()
    if conn is None or conn.transport not in ("hosted", "web") or allowed == set():
        return JSONResponse({"error": "No such connection for this run"}, status_code=404)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:                                   # notifications: nothing to say back
        return Response(status_code=202)
    every = webapi.TOOLS if conn.transport == "web" else {**google.TOOLS, **linkedin.TOOLS, **town.TOOLS}.get(conn.app, [])
    tools = [t for t in every if allowed is None or t["name"] in allowed]
    if method == "initialize":
        return _reply(mid, {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": f"agent-town-{conn.app or 'web'}", "version": "1.0"}})
    if method == "tools/list":
        return _reply(mid, {"tools": tools})
    if method == "tools/call":
        p = msg.get("params") or {}
        name, args = p.get("name", ""), p.get("arguments") or {}
        if name not in {t["name"] for t in tools}:
            return _reply(mid, error=(-32602, f"{name!r} isn't one of this connection's tools"))
        if conn.transport == "web":
            outbox.taint(r, f"It read what another app returned ({conn.name})")
            db.commit()
            try:
                return _reply(mid, {"content": [{"type": "text", "text": webapi.call(conn, name, args)}]})
            except (webapi.WebError, mcp_client.McpError, httpx.HTTPError) as e:
                return _reply(mid, {"isError": True, "content": [{"type": "text", "text": webapi.scrub(conn, f"{type(e).__name__}: {e}")}]})
        if conn.app == town.APP:                       # adding to their town waits for their Add (app/town.py)
            try:
                return _reply(mid, {"content": [{"type": "text", "text": town.call(db, r, name, args)}]})
            except town.TownError as e:
                return _reply(mid, {"isError": True, "content": [{"type": "text", "text": str(e)}]})
        acct = db.get(OAuthAccount, conn.oauth_account_id)
        if conn.app == "linkedin":
            return _linkedin(db, r, conn, acct, mid, name, args)
        try:
            if name in mailindex.NAMES:                # answered from the index, not by Google
                result = mailindex.call(db, acct, name, args)
            else:
                result = google.call(db, acct, conn.app, name, args)
            if name == "send_email":                  # a draft for now: the person's Send, or their rules, send it
                return _reply(mid, {"content": [{"type": "text", "text": outbox.queue(db, r, conn, acct, result, args)}]})
            if name in ("read_email", "search_emails", "find_people"):
                outbox.check_read(db, r, acct, name, result)
                db.commit()
            return _reply(mid, {"content": [{"type": "text", "text": google.tool_text(result)}]})
        except google.Expired:
            conn.status, conn.status_detail = "auth_required", "Google sign-in expired: connect again"
            db.commit()
            return _reply(mid, {"isError": True, "content": [{"type": "text", "text":
                              "The Google sign-in for this app has expired. Ask the person to connect it again in Agent Town."}]})
        except (google.GoogleError, KeyError, ValueError) as e:
            return _reply(mid, {"isError": True, "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}]})
    if method == "ping":
        return _reply(mid, {})
    return _reply(mid, error=(-32601, f"No method {method}"))


@router.post("/api/runtime/mail")
def mail_mcp(msg: dict = Body(...), r: Run = Depends(current_run), db: Session = Depends(get_db)):
    tools = mail.tools_for(db, r.agent)
    if not tools:
        return JSONResponse({"error": "No mail for this run"}, status_code=404)
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return Response(status_code=202)
    if method == "initialize":
        return _reply(mid, {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2025-06-18"),
                            "capabilities": {"tools": {}}, "serverInfo": {"name": "agent-town-mail", "version": "1.0"}})
    if method == "tools/list":
        return _reply(mid, {"tools": tools})
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            return _reply(mid, {"content": [{"type": "text", "text": mail.call(db, r, p.get("name", ""), p.get("arguments") or {})}]})
        except mail.MailError as e:
            db.rollback()
            return _reply(mid, {"isError": True, "content": [{"type": "text", "text": str(e)}]})
    if method == "ping":
        return _reply(mid, {})
    return _reply(mid, error=(-32601, f"No method {method}"))


def _linkedin(db: Session, r: Run, conn: McpConnection, acct: OAuthAccount, mid, name: str, args: dict) -> JSONResponse:
    try:
        result = linkedin.call(db, acct, name, args)
        if name == "create_post":                     # posted now, or held for the person: outbox decides
            return _reply(mid, {"content": [{"type": "text", "text": outbox.queue_post(db, r, conn, result)}]})
        return _reply(mid, {"content": [{"type": "text", "text": linkedin.tool_text(result)}]})
    except linkedin.Expired:
        conn.status, conn.status_detail = "auth_required", "LinkedIn sign-in ran out: connect again"
        db.commit()
        return _reply(mid, {"isError": True, "content": [{"type": "text", "text":
                          "The LinkedIn sign-in has run out. Ask the person to connect LinkedIn again in Agent Town."}]})
    except (linkedin.LinkedInError, httpx.HTTPError, ValueError) as e:
        return _reply(mid, {"isError": True, "content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}]})
