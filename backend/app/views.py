"""Rows -> JSON. Each function decides exactly what a given audience may see."""

import re

from . import mcp_auth, outbox
from .models import DEFINITION, Agent, AgentFile, ApiToken, McpConnection, ModelCredential, PublicShare, User
from .timeutil import iso


def frontmatter(text: str) -> tuple[dict[str, str], str]:
    """--- key: value --- header of a markdown file, as Claude Code agent files use."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"\'')
    return meta, text[m.end():]


def user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "email": u.email, "has_password": bool(u.password_hash),
            "google": bool(u.google_sub)}


def file_stats(f: AgentFile) -> dict:
    return {"id": f.id, "path": f.path, "lines": f.lines, "bytes": f.bytes,
            "updated_at": iso(f.updated_at)}


def file_full(f: AgentFile) -> dict:
    return {**file_stats(f), "content": f.content}


def agent_summary(a: Agent) -> dict:
    """Enough to draw the building: floors are files, floor height comes from lines."""
    return {"id": a.id, "slug": a.slug, "name": a.name, "description": a.description, "color": a.color,
            "owner": a.owner.username, "building": a.building, "files": [file_stats(f) for f in a.files],
            "lines": sum(f.lines for f in a.files)}


def agent_owner_view(a: Agent, share: PublicShare | None, file_shares: dict[int, int]) -> dict:
    return {**agent_summary(a), "can_use_public": a.can_use_public,
            "model_credential_id": a.model_credential_id, "model": a.model, "thinking": a.thinking,
            "memory": a.memory, "email_policy": outbox.policy(a), "post_policy": outbox.post_policy(a), "files": [{**file_full(f), "share_id": file_shares.get(f.id)} for f in a.files],
            "grants": [{"connection_id": g.connection_id, "tool_name": g.tool_name} for g in a.grants],
            "team": [m.id for m in a.team], "colony_name": a.colony_name, "colony_about": a.colony_about,
            "role": a.role, "share_id": share.id if share else None}     # role "mayor": it walks with them, no house


def connection(c: McpConnection, granted_to: list[dict] | None = None) -> dict:
    return {"id": c.id, "name": c.name, "transport": c.transport, "url": c.url, "command": c.command,
            "has_auth": bool(c.auth_header_enc), "app": c.app,
            # names only: the values are secrets
            "header_names": sorted({*mcp_auth.headers(c), *(["Authorization"] if c.auth_header_enc and c.transport == "http" else [])}), "env_names": sorted(mcp_auth.env(c)),
            "sign_in": mcp_auth.sign_in_state(c), "own_client": "client_id" in mcp_auth.oauth(c) and "registered_for" not in mcp_auth.oauth(c), "oauth_account_id": c.oauth_account_id, "status": c.status, "status_detail": c.status_detail,
            "server_name": c.server_name, "server_version": c.server_version,
            "last_checked_at": iso(c.last_checked_at),
            "tools": [{"name": t.name, "description": t.description} for t in c.tools],
            "granted_to": granted_to or []}


def share(s: PublicShare, with_content: bool = False) -> dict:
    out = {"id": s.id, "kind": s.kind, "title": s.title, "note": s.note, "owner": s.owner.username,
           "allow_agent_use": s.allow_agent_use, "created_at": iso(s.created_at)}
    if s.kind == "agent" and s.agent:
        out["agent"] = agent_summary(s.agent)
        if with_content:
            out["agent"]["files"] = [file_full(f) for f in s.agent.files]
    if s.kind == "file" and s.file:
        out["file"] = file_full(s.file) if with_content else file_stats(s.file)
        out["file"]["agent"] = s.file.agent.name
    return out


def definition(a: Agent) -> AgentFile | None:
    return next((f for f in a.files if f.path == DEFINITION), None)


def api_token(t: ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.prefix, "created_at": iso(t.created_at),
            "last_used_at": iso(t.last_used_at), "expires_at": iso(t.expires_at)}


def credential(c: ModelCredential) -> dict:
    """Never the secret: just enough to recognise it."""
    return {"id": c.id, "provider": c.provider, "kind": c.kind, "label": c.label, "hint": c.hint,
            "is_default": c.is_default, "status": c.status, "status_detail": c.status_detail,
            "last_checked_at": iso(c.last_checked_at), "created_at": iso(c.created_at)}
