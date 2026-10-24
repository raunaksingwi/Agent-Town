"""Is this model credential real? Checked with the provider's "list models" call: it needs a
valid key, costs nothing, and generates no tokens.

Subscription tokens can't be checked that way; they're verified when an agent first runs.
"""

import json
from dataclasses import dataclass

import httpx

CHECKS = {
    "anthropic": ("https://api.anthropic.com/v1/models",
                  lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"}),
    "openai": ("https://api.openai.com/v1/models", lambda key: {"Authorization": f"Bearer {key}"}),
}


@dataclass
class Checked:
    status: str      # valid | invalid | error | unverified
    detail: str


def shape_error(provider: str, kind: str, secret: str) -> str | None:
    """Catch the common paste mistakes before storing anything."""
    s = secret.strip()
    if provider == "anthropic" and kind == "api_key" and not s.startswith("sk-ant-api"):
        return "Anthropic API keys start with sk-ant-api… (console.anthropic.com → API keys)"
    if provider == "anthropic" and kind == "subscription" and not s.startswith("sk-ant-oat"):
        return "Run `claude setup-token` and paste the sk-ant-oat… token it prints"
    if provider == "openai" and kind == "api_key" and not s.startswith("sk-"):
        return "OpenAI API keys start with sk-… (platform.openai.com → API keys)"
    if provider == "openai" and kind == "subscription":
        try:
            data = json.loads(s)
        except ValueError:
            return "Paste the contents of ~/.codex/auth.json (run `codex login` first)"
        if not isinstance(data, dict) or "tokens" not in data:
            return "That auth.json has no tokens; run `codex login` with your ChatGPT account"
    return None


def check(provider: str, kind: str, secret: str, client: httpx.Client | None = None) -> Checked:
    if kind == "subscription":
        return Checked("unverified", "Subscription tokens are verified when an agent first runs")
    url, headers = CHECKS[provider]
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.get(url, headers=headers(secret.strip()))
        if r.status_code == 200:
            n = len((r.json() or {}).get("data") or [])
            return Checked("valid", f"Key works ({n} models available)")
        if r.status_code in (401, 403):
            return Checked("invalid", f"{provider} rejected the key (HTTP {r.status_code})")
        return Checked("error", f"{provider} answered HTTP {r.status_code}; try again later")
    except httpx.HTTPError as e:
        return Checked("error", f"Couldn't reach {provider}: {type(e).__name__}")
    finally:
        if own:
            client.close()
