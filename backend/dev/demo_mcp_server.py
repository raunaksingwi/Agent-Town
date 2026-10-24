"""A tiny MCP server over Streamable HTTP, written by hand so you can see the protocol.

    uv run uvicorn dev.demo_mcp_server:app --port 8765

Then add it in Agent Town as an http connection with url http://127.0.0.1:8765/mcp
(start the API with AGENTTOWN_ALLOW_PRIVATE_MCP_HOSTS=true, since it's on localhost).
Set DEMO_MCP_TOKEN=secret to make it demand "Authorization: Bearer secret".
Set DEMO_MCP_OAUTH=1 to make it want a sign-in instead, MCP-style: it serves its own protected-resource
and authorization-server metadata, lets any client register, and approves every sign-in at once.
Add ?sse=1 to the URL to get answers as an SSE stream instead of plain JSON.
"""

import base64
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

app = FastAPI(title="demo MCP server")
SESSIONS: set[str] = set()
CLIENTS: set[str] = set()
CODES: dict[str, str] = {}       # code -> the PKCE challenge it was issued for
TOKENS: set[str] = set()         # access tokens
REFRESH: set[str] = set()

TOOLS = [
    {"name": "echo", "description": "Repeat the text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "utc_now", "description": "The current time in UTC.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "word_count", "description": "Count the words in a piece of text.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
]


def call(name: str, args: dict) -> str:
    if name == "echo":
        return str(args.get("text", ""))
    if name == "utc_now":
        return datetime.now(timezone.utc).isoformat()
    if name == "word_count":
        return str(len(str(args.get("text", "")).split()))
    raise KeyError(name)


def reply(msg: dict, sse: bool, headers: dict | None = None) -> Response:
    if sse:
        return Response(f"event: message\ndata: {json.dumps(msg)}\n\n", media_type="text/event-stream",
                        headers=headers)
    return JSONResponse(msg, headers=headers)


def base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def oauth_on() -> bool:
    return os.environ.get("DEMO_MCP_OAUTH") == "1"


@app.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource(request: Request):
    if not oauth_on():
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"resource": base(request) + "/mcp", "authorization_servers": [base(request)], "scopes_supported": ["demo"]}


@app.get("/.well-known/oauth-authorization-server")
def authorization_server(request: Request):
    if not oauth_on():
        return JSONResponse({"error": "not found"}, status_code=404)
    b = base(request)
    return {"issuer": b, "authorization_endpoint": b + "/authorize", "token_endpoint": b + "/token",
            "registration_endpoint": b + "/register", "code_challenge_methods_supported": ["S256"]}


@app.post("/register")
async def register(request: Request):
    client_id = uuid.uuid4().hex
    CLIENTS.add(client_id)
    return JSONResponse({"client_id": client_id, **(await request.json())}, status_code=201)


@app.get("/authorize")
def authorize(client_id: str, redirect_uri: str, state: str, code_challenge: str):
    """A real app shows a consent screen here; the demo says yes straight away."""
    if client_id not in CLIENTS:
        return JSONResponse({"error": "invalid_client"}, status_code=400)
    code = uuid.uuid4().hex
    CODES[code] = code_challenge
    return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': state})}", status_code=302)


@app.post("/token")
async def token(request: Request):
    form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
    if form.get("grant_type") == "authorization_code":
        challenge = CODES.pop(form.get("code", ""), None)
        proof = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
        if challenge is None or proof != challenge:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
    elif form.get("grant_type") == "refresh_token":
        if form.get("refresh_token") not in REFRESH:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
    else:
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    access, refresh = uuid.uuid4().hex, uuid.uuid4().hex
    TOKENS.add(access)
    REFRESH.add(refresh)
    return {"access_token": access, "token_type": "Bearer", "expires_in": 3600, "refresh_token": refresh}


@app.post("/mcp")
async def mcp(request: Request):
    token = os.environ.get("DEMO_MCP_TOKEN")
    if token and request.headers.get("authorization") != f"Bearer {token}":
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers={"WWW-Authenticate": 'Bearer realm="demo"'})
    if oauth_on() and request.headers.get("authorization", "")[7:] not in TOKENS:
        meta = base(request) + "/.well-known/oauth-protected-resource/mcp"
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers={"WWW-Authenticate": f'Bearer resource_metadata="{meta}"'})
    sse = request.query_params.get("sse") == "1"
    msg = await request.json()
    method, mid = msg.get("method"), msg.get("id")

    if mid is None:  # a notification, e.g. notifications/initialized: acknowledge, no body
        return Response(status_code=202)
    if method == "initialize":
        sid = uuid.uuid4().hex
        SESSIONS.add(sid)
        return reply({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": msg["params"].get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "demo-mcp", "version": "0.1.0"}}}, sse, {"Mcp-Session-Id": sid})
    if request.headers.get("mcp-session-id") not in SESSIONS:
        return JSONResponse({"jsonrpc": "2.0", "id": mid, "error": {"code": -32600, "message": "No session"}},
                            status_code=404)
    if method == "tools/list":
        return reply({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}, sse)
    if method == "tools/call":
        p = msg.get("params") or {}
        try:
            text = call(p.get("name", ""), p.get("arguments") or {})
        except KeyError:
            return reply({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unknown tool"}}, sse)
        return reply({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}]}}, sse)
    return reply({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"No method {method}"}}, sse)


@app.delete("/mcp")
async def end(request: Request):
    SESSIONS.discard(request.headers.get("mcp-session-id", ""))
    return Response(status_code=204)
