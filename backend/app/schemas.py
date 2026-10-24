"""What the API accepts. Validation lives here so the routers can trust their input."""

import posixpath
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, EmailStr, Field, StringConstraints

Slug = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,29}$")
Color = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
MAX_FILE = 200_000
MAX_MEMORY = 20_000


def _first_name(v: str | None) -> str | None:
    v = " ".join((v or "").split())
    if not v:
        return None
    if len(v) > 30 or not v[0].isalpha() or not all(c.isalpha() or c in " '-" for c in v):
        raise ValueError("a name: letters, spaces, ' and -, up to 30 characters")
    return v


AssistantName = Annotated[str | None, AfterValidator(_first_name)]


class StarterIn(BaseModel):
    assistant_name: AssistantName = None  # what they call their mayor, the agent they start with ("" or none: mayor)


class SignupIn(StarterIn):
    email: EmailStr
    username: str = Slug
    password: str = Field(min_length=8, max_length=200)
    starter: bool = False  # move the starter town in (the app asks for it; the API alone starts empty)


class LoginIn(BaseModel):
    login: str = Field(min_length=1, description="email or username")
    password: str


FILE_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./ -]*\.(md|txt)$")


def file_path_problem(path: str) -> str | None:
    """Why a file path can't be stored, or None. A path is written into a sandbox at exactly this
    name, so it must stay inside the folder it's given: no "..", no hidden parts, nothing absolute."""
    if not FILE_PATH.fullmatch(path):
        return "a path like notes/playbook.md (letters, digits, _ . - and spaces; .md or .txt)"
    parts = path.split("/")
    if any(s == "" or s.startswith(".") or s.strip() != s for s in parts):
        return "no empty, hidden (starting with .) or padded parts in a path"
    if posixpath.normpath(path) != path:
        return "no .. or ./ in paths"
    return None


def _file_path(v: str) -> str:
    if problem := file_path_problem(v):
        raise ValueError(problem)
    return v


FilePath = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_file_path)]


class FileIn(BaseModel):
    path: FilePath
    content: str = Field(max_length=MAX_FILE)


class AgentIn(BaseModel):
    markdown: str = Field(min_length=1, max_length=MAX_FILE, description="AGENT.md: the agent's definition")
    name: str | None = Field(default=None, max_length=80)
    color: str | None = Color
    files: list[FileIn] = Field(default_factory=list, max_length=50)


def _allow_entry(v: str) -> str:
    v = v.strip().lower()
    if not re.fullmatch(r"@?([^@\s]+@)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}", v) or len(v) > 320:
        raise ValueError("an email address (sam@acme.com) or a domain (acme.com)")
    return v


AllowEntry = Annotated[str, AfterValidator(_allow_entry)]


class EmailPolicy(BaseModel):
    """When an email this agent sends may go out without the owner pressing Send (app/outbox.py)."""
    mode: Literal["ask", "auto"] = "ask"
    to: Literal["known", "anyone"] = "known"
    allow: list[AllowEntry] = Field(default_factory=list, max_length=100, description="addresses or domains")
    replies_only: bool = False


class PostPolicy(BaseModel):
    """Whether a LinkedIn post this agent writes goes out at once or waits for the owner (app/outbox.py)."""
    mode: Literal["ask", "auto"] = "auto"


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    color: str | None = Color
    can_use_public: bool | None = None
    model_credential_id: int | None = Field(default=None, description="0 = use your default")
    model: str | None = Field(default=None, max_length=100, pattern=r"^[A-Za-z0-9._:/@-]*$")
    thinking: Literal["", "low", "medium", "high", "xhigh", "max"] | None = None
    building: Literal["", "studio", "office", "forge", "library", "lab", "observatory", "tavern", "cottage", "tower"] | None = None
    memory: str | None = Field(default=None, max_length=MAX_MEMORY)
    email_policy: EmailPolicy | None = None
    post_policy: PostPolicy | None = None
    colony_name: str | None = Field(default=None, max_length=60)
    colony_about: str | None = Field(default=None, max_length=300)


class GrantIn(BaseModel):
    connection_id: int
    tool_name: str | None = None  # None: every tool on the connection


class GrantsIn(BaseModel):
    grants: list[GrantIn] = Field(max_length=500)


class TeamIn(BaseModel):
    member_ids: list[int] = Field(max_length=50)


Secrets = dict[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,100}$")], Annotated[str, StringConstraints(max_length=8000)]]


class McpIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    transport: Literal["http", "stdio", "web"] = "http"  # web: a read-only API Agent Town calls
    url: str | None = Field(default=None, max_length=2000)
    command: str | None = Field(default=None, max_length=2000)
    auth_header: str | None = Field(default=None, max_length=4000,
                                    description='e.g. "Bearer sk-…". Stored encrypted, never returned')
    headers: Secrets = Field(default_factory=dict, max_length=50, description="http: other headers, stored encrypted")
    env: Secrets = Field(default_factory=dict, max_length=50, description="stdio: its environment, stored encrypted")
    # for an app that won't register Agent Town itself: a client from its developer settings
    oauth_client_id: str | None = Field(default=None, max_length=400)
    oauth_client_secret: str | None = Field(default=None, max_length=4000)


class McpPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    url: str | None = Field(default=None, max_length=2000)
    command: str | None = Field(default=None, max_length=2000)
    auth_header: str | None = Field(default=None, max_length=4000, description='"" removes it')
    headers: Secrets | None = Field(default=None, max_length=50, description="replaces them all; {} removes them")
    env: Secrets | None = Field(default=None, max_length=50, description="replaces it all; {} removes it")
    oauth_client_id: str | None = Field(default=None, max_length=400, description='"" goes back to registering itself')
    oauth_client_secret: str | None = Field(default=None, max_length=4000)


class McpImportIn(BaseModel):
    text: str = Field(min_length=2, max_length=200_000, description=".mcp.json, Claude Desktop config or Codex config.toml")


class ShareIn(BaseModel):
    kind: Literal["agent", "file"]
    agent_id: int | None = None
    file_id: int | None = None
    title: str | None = Field(default=None, max_length=120)
    note: str = Field(default="", max_length=2000)
    allow_agent_use: bool = True


class SharePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=2000)
    allow_agent_use: bool | None = None


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    expires_days: int | None = Field(default=90, ge=1, le=3650, description="None = never expires")


class CredentialIn(BaseModel):
    provider: Literal["anthropic", "openai"]
    kind: Literal["api_key", "subscription"] = "api_key"
    label: str | None = Field(default=None, max_length=80)
    secret: str = Field(min_length=8, max_length=20_000)


class CredentialPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    is_default: bool | None = None


# a building on the map, or a room on the Office floor (room:<lead id>, room:agents, room:empty-<n>)
TownKey = Annotated[str, StringConstraints(pattern=r"^((agent|station|shared):\d{1,12}|files|library|room:(\d{1,12}|agents|empty-\d{1,3}))$")]
Coord = Annotated[float, Field(ge=-500, le=500, allow_inf_nan=False)]


class TownIn(BaseModel):
    """Where the user moved buildings on their map, in tiles from the town square, and rooms on the
    Office floor, in 8 px steps from the reception's middle."""
    positions: dict[TownKey, tuple[Coord, Coord]] = Field(max_length=1000)


class EmptyColony(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    about: str = Field(default="", max_length=300)


class EmptyColoniesIn(BaseModel):
    """Colonies named but with no agents yet. The whole list each time, like TownIn."""
    colonies: list[EmptyColony] = Field(max_length=50)


class PreferencesIn(BaseModel):
    map_style: Literal["retro", "fantasy", "office"] | None = None
