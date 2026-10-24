"""Read the MCP servers out of a config someone already has, so they don't retype them:

  Claude Code   .mcp.json, `claude mcp add-json`, a plugin's .mcp.json or plugin.json
                {"mcpServers": {"name": {"type": "http", "url": …, "headers": {…}}}}
  Claude Desktop, Cursor, Windsurf: the same {"mcpServers": …}, often with "command"/"args"/"env"
  VS Code       {"servers": {…}} (or {"mcp": {"servers": …}} in settings.json)
  Codex         ~/.codex/config.toml: [mcp_servers.name] with url / command, args, env, http_headers

Values like ${GITHUB_TOKEN} or a Codex `bearer_token_env_var` point at the person's own environment,
which we don't have: those come back as warnings, so they can fill them in.
"""

import json
import re
import shlex
import tomllib

PLACEHOLDER = re.compile(r"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?")


class NotAConfig(ValueError):
    pass


def _servers(doc: dict) -> dict:
    for path in (("mcpServers",), ("mcp_servers",), ("servers",), ("mcp", "servers")):
        d = doc
        for k in path:
            d = d.get(k) if isinstance(d, dict) else None
        if isinstance(d, dict):
            return d
    if "url" in doc or "command" in doc:                     # one server on its own
        return {str(doc.get("name") or "server"): doc}
    if doc and all(isinstance(v, dict) and ("url" in v or "command" in v) for v in doc.values()):
        return doc                                            # just the inside of "mcpServers"
    raise NotAConfig("No MCP servers in there. Paste a .mcp.json, a Claude Desktop config or a Codex config.toml.")


def parse(text: str) -> list[dict]:
    """Each server as {name, transport, url, command, headers, env, warnings}."""
    text = text.strip()
    try:
        doc = json.loads(text)
    except ValueError:
        try:
            doc = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            raise NotAConfig(f"That isn't JSON or TOML: {e}") from e
    if not isinstance(doc, dict):
        raise NotAConfig("Expected an object of MCP servers")

    out = []
    for name, s in _servers(doc).items():
        if not isinstance(s, dict) or s.get("enabled") is False or s.get("disabled") is True:
            continue
        warnings = []
        headers = {str(k): str(v) for k, v in (s.get("headers") or s.get("http_headers") or {}).items()}
        env = {str(k): str(v) for k, v in (s.get("env") or {}).items()}
        if s.get("bearer_token_env_var"):                    # Codex: the token is in an env var
            warnings.append(f"needs the token from ${s['bearer_token_env_var']}: add it as the Authorization header")
        for h, var in (s.get("env_http_headers") or {}).items():
            warnings.append(f"header {h} comes from ${var}: add its value")
        if s.get("url"):
            if str(s.get("type") or s.get("transport") or "").lower() == "sse":
                warnings.append("uses the older SSE transport; if it won't connect, try its /mcp address")
            item = {"name": str(name), "transport": "http", "url": str(s["url"]), "command": None,
                    "headers": headers, "env": {}}
        elif s.get("command"):
            args = [str(a) for a in s.get("args") or []]
            item = {"name": str(name), "transport": "stdio", "url": None,
                    "command": shlex.join([str(s["command"]), *args]), "headers": {}, "env": env}
        else:
            continue
        for k, v in {**item["headers"], **item["env"]}.items():
            if PLACEHOLDER.search(v):
                warnings.append(f"{k} is {v}: put in the real value")
        item["warnings"] = warnings
        out.append(item)
    if not out:
        raise NotAConfig("No servers with a url or a command in there")
    return out
