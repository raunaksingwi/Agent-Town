"""A read-only web API that Agent Town calls on an agent's behalf (connections with transport "web").

The owner gives a base URL and an Authorization header. Agents get one tool, `get`: a GET request
to a path under that base. Agent Town adds the header here, so it never reaches the sandbox or the
model; nothing but GET is possible, and a request can't leave the base URL.

The base URL is a secret too: some APIs put their key in the path (/api/v1/admin-<key>). It's stored
encrypted like the header, and the app only ever shows its scheme and host.
"""

import posixpath
from urllib.parse import unquote, urlparse

import httpx

from . import mcp_client
from .config import settings
from .security import decrypt, encrypt

MAX_TEXT = 20_000

TOOLS = [
    {"name": "get", "description": "Read from this web API (GET only). `path` is relative to the API's base URL, "
                                   "e.g. /dashboard; put query parameters in `query`, not in the path. Returns the "
                                   f"HTTP status and the response body, cut at {MAX_TEXT:,} characters.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string", "description": "Starts with /, e.g. /users"},
         "query": {"type": "object", "additionalProperties": {"type": ["string", "number", "boolean"]}}}}},
]


class WebError(Exception):
    pass


def http() -> httpx.Client:
    # no redirects: following one would hand the Authorization header to wherever it points
    return httpx.Client(timeout=30, follow_redirects=False)


def shown(url: str) -> str:
    """What the app shows for a base URL: scheme and host, never the path or query that may hold a key."""
    u = urlparse(url)
    if not u.scheme or not u.netloc:
        return "…"
    host = u.netloc.rsplit("@", 1)[-1]                # user:password@host
    return f"{u.scheme}://{host}" + ("/…" if u.path.strip("/") or u.query else "")


def set_base(conn, url: str) -> None:
    conn.url_enc, conn.url = encrypt(url), shown(url)


def base_url(conn) -> str:
    """The real base URL. Raises if it can't be decrypted (the secret key changed)."""
    if not conn.url_enc:
        return conn.url or ""
    url = decrypt(conn.url_enc)
    if url is None:
        raise WebError("The stored URL can't be decrypted: save it again in Agent Town")
    return url


def scrub(conn, text: str) -> str:
    """An error message with the base URL swapped for what the app shows of it."""
    try:
        base = base_url(conn)
    except WebError:
        return text
    return text.replace(base.rstrip("/"), conn.url or "…") if base else text


def url_for(base: str, path: str) -> str:
    """base + path, refusing anything that could point somewhere else (another host, ../, a query)."""
    if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?#\\"):
        raise WebError("path must start with / and hold only a path: no ?, # or \\; use `query` for parameters")
    # servers decode %2e%2e and collapse dot segments, so check what they would see
    plain = unquote(path)
    if posixpath.normpath(plain) != plain.rstrip("/") and posixpath.normpath(plain) != plain:
        raise WebError("path must not hold . or .. segments")
    url = base.rstrip("/") + path
    base_path = urlparse(base).path.rstrip("/")
    if urlparse(url).netloc != urlparse(base).netloc or not posixpath.normpath(urlparse(unquote(url)).path).startswith(base_path):
        raise WebError("path must stay under the API's URL")
    return url


def check(base: str) -> tuple[str, str]:
    """(status, detail) for the station card. Doesn't call the API: any request might be audited or cost."""
    try:
        mcp_client.guard_url(base, settings().allow_private_mcp_hosts)
    except mcp_client.McpError as e:
        return "error", str(e)
    return "connected", "Agent Town calls it for your agents: GET only, under this URL"


def sync_tools(conn) -> None:
    from .models import McpTool
    conn.tools = [t for t in conn.tools if t.name in {x["name"] for x in TOOLS}]
    have = {t.name for t in conn.tools}
    conn.tools += [McpTool(name=t["name"], description=t["description"], input_schema=t["inputSchema"])
                   for t in TOOLS if t["name"] not in have]


def call(conn, name: str, args: dict) -> str:
    if name != "get":
        raise WebError(f"No tool {name!r}")
    base = base_url(conn)
    url = url_for(base, str(args.get("path", "")))
    mcp_client.guard_url(base, settings().allow_private_mcp_hosts)
    headers = {"Accept": "application/json, text/plain;q=0.9, */*;q=0.5"}
    if conn.auth_header_enc:
        auth = decrypt(conn.auth_header_enc)
        if auth is None:
            raise WebError("The stored Authorization header can't be decrypted: save it again in Agent Town")
        headers["Authorization"] = auth
    query = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in (args.get("query") or {}).items()}
    with http() as c:
        r = mcp_client.fetch(c, "GET", url, params=query, headers=headers)
    body = r.text
    if len(body) > MAX_TEXT:
        body = body[:MAX_TEXT] + f"\n… cut: {len(r.text):,} characters in all"
    return f"HTTP {r.status_code}\n{body}"
