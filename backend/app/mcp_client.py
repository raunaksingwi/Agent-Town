"""Talk to an MCP server over Streamable HTTP, just enough to check it and list its tools.

No SDK on purpose, so the protocol is visible. One check is three JSON-RPC messages:

  1. initialize                 -> server name/version/capabilities, maybe an Mcp-Session-Id header
  2. notifications/initialized  (a notification: no id, no reply expected)
  3. tools/list                 -> the tools, paged with nextCursor

A server may answer a POST with plain JSON or with an SSE stream (text/event-stream) whose
`data:` lines carry the JSON-RPC response. Both are handled.
Spec: https://modelcontextprotocol.io/specification (Transports, Lifecycle, Tools).
"""

import ipaddress
import json
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = 10.0


@dataclass
class CheckResult:
    status: str                        # connected | auth_required | error
    detail: str = ""
    server_name: str = ""
    server_version: str = ""
    tools: list[dict] = field(default_factory=list)
    www_authenticate: str = ""         # auth_required: where the server says to sign in


class McpError(Exception):
    pass


def guard_url(url: str, allow_private: bool) -> None:
    """Refuse URLs that would make this server attack its own network (SSRF).
    Note: a hostile DNS server can still answer differently on the real request (DNS rebinding).
    The sandbox egress proxy is the real fix once agents make these calls themselves."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise McpError("URL must be http(s)://host/…")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror as e:
        raise McpError(f"Can't resolve {u.hostname}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise McpError(f"{u.hostname} resolves to a private address ({ip}); "
                           "set AGENTTOWN_ALLOW_PRIVATE_MCP_HOSTS=true for local development")


MAX_BODY = 2_000_000   # a tool list or a token reply is kilobytes; read no more than this from anyone


def fetch(client: httpx.Client, method: str, url: str, limit: int = MAX_BODY, **kw) -> httpx.Response:
    """A request whose reply is read at most `limit` bytes, so a slow or hostile server can't fill
    memory. Same Response as client.request would give, just cut short."""
    with client.stream(method, url, **kw) as r:
        body = b""
        for chunk in r.iter_bytes():
            body += chunk
            if len(body) > limit:
                break
    return httpx.Response(r.status_code, headers=r.headers, content=body[:limit], request=r.request)


def _parse(resp: httpx.Response, want_id: int) -> dict:
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if msg.get("id") == want_id:
                    return msg
        raise McpError("SSE stream ended without a response")
    try:
        return resp.json()
    except ValueError as e:
        raise McpError(f"Not JSON (content-type {ctype or 'none'})") from e


def check(url: str, extra_headers: dict[str, str] | None = None, *, allow_private: bool = False,
          client: httpx.Client | None = None) -> CheckResult:
    try:
        guard_url(url, allow_private)
    except McpError as e:
        return CheckResult("error", str(e))

    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json",
               "MCP-Protocol-Version": PROTOCOL_VERSION}
    headers.update(extra_headers or {})
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=False)
    try:
        r = fetch(client, "POST", url, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "agent-town", "version": "0.1.0"}}})
        if r.status_code in (401, 403):
            hint = r.headers.get("www-authenticate", "")
            return CheckResult("auth_required", f"HTTP {r.status_code}. The server wants credentials"
                               + (f" ({hint[:200]})" if hint else ""), www_authenticate=hint)
        if r.status_code >= 400:
            return CheckResult("error", f"initialize: HTTP {r.status_code}")
        init = _parse(r, 1)
        if "error" in init:
            return CheckResult("error", f"initialize: {init['error'].get('message', init['error'])}")
        info = (init.get("result") or {}).get("serverInfo") or {}
        sid = r.headers.get("mcp-session-id")
        if sid:
            headers["Mcp-Session-Id"] = sid
        client.post(url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools, cursor, req_id = [], None, 2
        while True:
            params = {"cursor": cursor} if cursor else {}
            r = fetch(client, "POST", url, headers=headers,
                      json={"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": params})
            if r.status_code >= 400:
                return CheckResult("error", f"tools/list: HTTP {r.status_code}")
            msg = _parse(r, req_id)
            if "error" in msg:
                return CheckResult("error", f"tools/list: {msg['error'].get('message', msg['error'])}")
            result = msg.get("result") or {}
            tools += result.get("tools") or []
            cursor = result.get("nextCursor")
            req_id += 1
            if not cursor or req_id > 50:
                break
        if sid:  # be polite: end the session
            try:
                client.delete(url, headers=headers)
            except httpx.HTTPError:
                pass
        return CheckResult("connected", f"{len(tools)} tools", info.get("name", ""),
                           info.get("version", ""), tools)
    except httpx.HTTPError as e:
        return CheckResult("error", f"{type(e).__name__}: {e}")
    except McpError as e:
        return CheckResult("error", str(e))
    finally:
        if own:
            client.close()
