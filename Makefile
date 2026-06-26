# Local data management. OSINT_DATA_DIR defaults to ./data (see .env).
# Resolve OSINT_DATA_DIR: explicit env > .env file > ./data default.
OSINT_DATA_DIR ?= $(shell sed -n 's/^OSINT_DATA_DIR=//p' .env 2>/dev/null)
OSINT_DATA_DIR := $(if $(strip $(OSINT_DATA_DIR)),$(OSINT_DATA_DIR),./data)

.PHONY: up down logs data-size data-prune data-reset

up:  ## Start the whole backend (stores + worker + beat + API) in the background
	@bash scripts/dev-up.sh

down:  ## Stop the backend processes + Docker stores (keeps data)
	@bash scripts/dev-down.sh

logs:  ## Tail the background backend logs (Ctrl-C to stop tailing; stack keeps running)
	@tail -n 40 -F logs/*.log

data-size:  ## Show disk used by each data subfolder
	@du -sh $(OSINT_DATA_DIR)/* 2>/dev/null || echo "no data yet at $(OSINT_DATA_DIR)"

data-prune:  ## Run retention housekeeping now
	.venv/bin/python scripts/prune_now.py

data-reset:  ## Stop stack and wipe all local data (DESTRUCTIVE)
	@test -n "$(strip $(OSINT_DATA_DIR))" || { echo "OSINT_DATA_DIR is empty — refusing to delete"; exit 1; }
	docker compose down
	rm -rf $(OSINT_DATA_DIR)
	@echo "wiped $(OSINT_DATA_DIR)"
