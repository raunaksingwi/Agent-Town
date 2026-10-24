# One image, one process: the API serves the built frontend (see backend/app/main.py).
# In production agents don't run here: each run gets its own Modal Sandbox (backend/app/sandbox.py).
# The `local` target is for running your own town on your computer (docker-compose.yml): it adds
# Claude Code and Codex so agents run inside this container instead.

FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY PRIVACY.md TERMS.md /app/
RUN npm run build

FROM python:3.12-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --group modal --no-install-project
COPY backend/ ./
COPY agents/ /app/agents/
COPY AGENTS.md CARETAKER.md /app/
COPY --from=web /app/frontend/dist /app/frontend/dist
RUN useradd --create-home app
USER app
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]

# Your own town on your computer: agents run as processes in this container (docker-compose.yml).
FROM app AS local
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates git \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code @openai/codex && rm -rf /var/lib/apt/lists/* /root/.npm
USER app

# The default (last) target: what Render builds.
FROM app AS production
