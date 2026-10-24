"""Put a Google OAuth client into backend/.env without the secret ever being printed.

    cd backend
    uv run python scripts/import_google_client.py ~/Downloads/client_secret_XXXX.json

Reads the client_secret.json you downloaded from Google Cloud (Google Auth Platform → Clients),
writes AGENTTOWN_GOOGLE_CLIENT_ID and AGENTTOWN_GOOGLE_CLIENT_SECRET into backend/.env (replacing
old values), and checks the redirect URI Agent Town will use is registered. backend/.env is
gitignored. Afterwards you can delete the downloaded file. On Render, paste the same two values
into the service's Environment settings instead.
"""

import json
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    src = Path(sys.argv[1]).expanduser().resolve()
    try:
        data = json.loads(src.read_text())
    except FileNotFoundError:
        print(f"No file at {src}. Google names it client_secret_<id>.apps.googleusercontent.com.json.")
        return 1
    except PermissionError:
        print(f"macOS won't let this program read {src.parent} (privacy protection for Downloads, Desktop and\n"
              "Documents). Run this in your own Terminal app, or move the file to your home folder first.")
        return 1
    client = data.get("web") or data.get("installed")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        print("That file has no client_id/client_secret. Download the JSON of an OAuth client from Google Cloud.")
        return 1
    if "web" not in data:
        print('Note: this is a "Desktop" client. Agent Town needs a "Web application" client for its redirect URI.')

    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith(("AGENTTOWN_GOOGLE_CLIENT_ID=", "AGENTTOWN_GOOGLE_CLIENT_SECRET="))]
    lines += ["# Google OAuth client (imported by scripts/import_google_client.py; never commit)",
              f"AGENTTOWN_GOOGLE_CLIENT_ID={client['client_id']}",
              f"AGENTTOWN_GOOGLE_CLIENT_SECRET={client['client_secret']}"]
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)

    app_url = next((ln.split("=", 1)[1] for ln in lines if ln.startswith("AGENTTOWN_APP_URL=")), "http://127.0.0.1:8000")
    wanted = app_url.rstrip("/") + "/api/connect/google/callback"
    registered = client.get("redirect_uris", [])
    print(f"Saved to {ENV} (client id ends …{client['client_id'][-28:]}, secret hidden)")
    print("Redirect URIs on this client:", *[f"  {u}" for u in registered] or ["  (none)"], sep="\n")
    if wanted in registered:
        print(f"OK: {wanted} is registered.")
    else:
        print(f"Add this one in Google Cloud → Clients → your client → Authorized redirect URIs:\n  {wanted}")
    if REPO in src.parents:
        print(f"Warning: {src.name} is inside the repo. It's gitignored, but better to move it out (or delete it).")
    print("Restart the API to pick it up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
