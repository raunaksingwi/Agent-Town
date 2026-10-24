"""Settings, read from the environment (or backend/.env). Every knob the app has lives here."""

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET = "dev-only-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AGENTTOWN_", extra="ignore")

    # sqlite for local dev; point at Postgres in production:
    #   AGENTTOWN_DATABASE_URL=postgresql+psycopg://user:pass@host/agenttown
    database_url: str = "sqlite:///./agenttown.db"

    # Encrypts MCP credentials at rest. Changing it makes stored credentials unreadable.
    secret_key: str = DEV_SECRET

    session_days: int = 30
    # Let people make an account with an email and password. Nobody checks that email is theirs, so
    # where Google sign-in is set up you may want it off: then new accounts come only through Google,
    # which has. Accounts that already have a password still sign in with it.
    password_signup: bool = True
    # Who may make a new account: emails and whole domains, comma-separated
    # ("sam@acme.com, @designpartner.com"). Empty: anyone. Existing accounts are never locked out.
    allowed_emails: str = ""
    # Serve the interactive API docs at /docs. Handy in development; off in production (render.yaml).
    api_docs: bool = True
    # True behind HTTPS so the session cookie is never sent in clear text.
    cookie_secure: bool = False

    # Checking an MCP server means this server makes an HTTP request to a URL a user typed.
    # Off by default so nobody can point it at 127.0.0.1 / 10.x / cloud metadata (SSRF).
    # Turn on for local development against a server on your machine.
    allow_private_mcp_hosts: bool = False

    # Let users store a *subscription* token (Claude `setup-token`, Codex auth.json) as well as an
    # API key. Each run uses only its owner's token, in that owner's own sandbox. The provider's
    # terms are between the user and the provider; the UI says so when they add one.
    allow_subscription_tokens: bool = True

    # Where agents run: "local" (a subprocess on this machine: development only, NOT isolated)
    # or "modal" (a Modal Sandbox per run; needs `uv sync --group modal` and MODAL_TOKEN_ID/SECRET).
    sandbox_provider: str = "local"
    # How a sandbox reaches this API. Must be reachable from inside the sandbox (public in production).
    # On Render it defaults to the service's own https URL, which Render sets as RENDER_EXTERNAL_URL.
    public_url: str = os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000"
    # A run with nobody talking to it stops after this; a run never lives longer than run_max_hours.
    run_idle_minutes: int = 15
    run_max_hours: int = 4
    # Start routines when they're due (app/routines.py). Every API process may run it: each routine is
    # claimed by exactly one. Turn off for a process that should only serve requests.
    scheduler: bool = True

    # Where people open Agent Town in their browser. "Sign in with Google" sends them back here, so
    # this host must match a redirect URI registered on the Google client. On Render: the service URL.
    app_url: str = os.environ.get("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000"
    # Your Google OAuth client (Google Cloud → Google Auth Platform → Clients). Empty: Gmail and
    # Calendar show "not set up on this server". Import a client_secret.json with
    # `uv run python scripts/import_google_client.py <file>`; never commit these.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Your LinkedIn app (linkedin.com/developers → My apps), with the "Sign In with LinkedIn using
    # OpenID Connect" and "Share on LinkedIn" products. Empty: LinkedIn shows "not set up on this server".
    linkedin_client_id: str = ""
    linkedin_client_secret: str = ""
    # LinkedIn's API is versioned by month (YYYYMM); each version works for at least a year.
    linkedin_api_version: str = "202607"

    def email_allowed(self, email: str) -> bool:
        entries = {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}
        email = email.strip().lower()
        return not entries or email in entries or "@" + email.rpartition("@")[2] in entries

    @field_validator("database_url")
    @classmethod
    def _psycopg(cls, v: str) -> str:
        """Hosts (Render, Heroku…) hand out postgres:// URLs; SQLAlchemy needs the driver named."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


@lru_cache
def settings() -> Settings:
    return Settings()
