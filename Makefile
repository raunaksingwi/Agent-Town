# Your own Agent Town on this computer, with Docker. Data is kept between restarts.
#
#   make up        build (first time, or after pulling new code) and start
#   make stop      turn it off (data kept)
#   make start     turn it back on
#   make status    is it running, and the address for friends on your Wi-Fi
#   make logs      follow the app's log
#   make share     open an ngrok tunnel to AGENTTOWN_APP_URL (set it in .env.local first)
#   make backup    save the database to backups/agenttown-<date>.sql
#   make restore FILE=backups/<file>.sql   load a backup (replaces what's there now)
#   make destroy   delete everything, data included (asks first)
#
#   make dev       development instead: API + website with live reload, data in backend/agenttown.db
#
# Your secrets live in .env.local (git-ignored), made by the first `make up`. Keep
# AGENTTOWN_SECRET_KEY: it encrypts the AI accounts and app sign-ins people save.

SHELL := /bin/bash
ENV ?= .env.local
# read the settings without letting make try to build the file (only `make up` does that)
ifneq ($(wildcard $(ENV)),)
include $(ENV)
endif
PORT := $(or $(AGENTTOWN_PORT),8000)
COMPOSE := AGENTTOWN_ENV_FILE=$(ENV) docker compose --env-file $(ENV)
LAN_IP := $(shell ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

.PHONY: help env up start stop status logs share backup restore destroy dev
.DEFAULT_GOAL := help

help:
	@sed -n '3,14p' Makefile | sed 's/^# \{0,1\}//'

# Made once, never overwritten: a new key and database password, plus your Google sign-in keys
# from development if backend/.env has them (copied, never printed).
env:
	@[ -f $(ENV) ] && exit 0; umask 077; rand() { python3 -c "import secrets; print(secrets.token_urlsafe($$1))"; }; { \
	  echo "# Your local Agent Town (made by make up). Never commit this file."; \
	  echo "AGENTTOWN_SECRET_KEY=$$(rand 48)"; \
	  echo "AGENTTOWN_DB_PASSWORD=$$(rand 24)"; \
	  echo "AGENTTOWN_ALLOW_SUBSCRIPTION_TOKENS=true"; \
	  echo "AGENTTOWN_PORT=$(PORT)"; \
	  echo "# The address people open. Set it to your tunnel's https address to share (make share)."; \
	  echo "AGENTTOWN_APP_URL=http://127.0.0.1:$(PORT)"; \
	} > $(ENV); \
	if [ -f backend/.env ]; then grep -E '^AGENTTOWN_GOOGLE_CLIENT_(ID|SECRET)=' backend/.env >> $(ENV) || true; fi; \
	echo "Made $(ENV) with a new secret key. Back it up somewhere safe along with your backups."

define running
	@echo "Agent Town is running: http://127.0.0.1:$(PORT)"
	@$(if $(LAN_IP),echo "Friends on the same Wi-Fi: http://$(LAN_IP):$(PORT)",true)
endef

up: env
	$(COMPOSE) up -d --build
	$(running)

start:
	@[ -f $(ENV) ] || { echo "Run make up first."; exit 1; }
	$(COMPOSE) start
	$(running)

stop:
	$(COMPOSE) stop
	@echo "Stopped. Your data is kept; make start brings it back."

status:
	$(COMPOSE) ps
	@$(if $(LAN_IP),echo "Friends on the same Wi-Fi: http://$(LAN_IP):$(PORT)",true)

logs:
	$(COMPOSE) logs -f app

share:
	@case "$(AGENTTOWN_APP_URL)" in https://*) ;; \
	  *) echo "Set AGENTTOWN_APP_URL in $(ENV) to your ngrok address (https://...), then make up."; exit 1;; esac
	ngrok http --url=$(AGENTTOWN_APP_URL) $(PORT)

backup:
	@mkdir -p backups
	@f=backups/agenttown-$$(date +%Y%m%d-%H%M%S).sql; \
	  $(COMPOSE) exec -T db pg_dump -U agenttown --clean --if-exists agenttown > $$f && echo "Saved $$f"

restore:
	@[ -f "$(FILE)" ] || { echo "Usage: make restore FILE=backups/<file>.sql"; exit 1; }
	$(COMPOSE) exec -T db psql -q -U agenttown -d agenttown < $(FILE)
	$(COMPOSE) restart app
	@echo "Restored $(FILE)"

destroy:
	@read -r -p "Delete your local town AND all its data? Type 'delete' to confirm: " ok; \
	  [ "$$ok" = delete ] && $(COMPOSE) down -v && echo "Deleted. ($(ENV) and backups/ are still here.)"

# Development: the API (uvicorn, port 8000) and the website (Vite) together, both reloading on
# save. Ctrl-C stops both. Uses backend/.env, not $(ENV), so it can't run alongside `make up`.
dev:
	@if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then echo "Port 8000 is busy (is the Docker town on? make stop)"; exit 1; fi
	@[ -d frontend/node_modules ] || (cd frontend && npm install)
	@trap 'kill 0' INT TERM EXIT; \
	  (cd backend && uv run --group modal python -m uvicorn app.main:app --reload --port 8000) & \
	  (cd frontend && npm run dev) & \
	  wait
