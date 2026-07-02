# Local data management. OSINT_DATA_DIR defaults to ./data (see .env).
# Resolve OSINT_DATA_DIR: explicit env > .env file > ./data default.
OSINT_DATA_DIR ?= $(shell sed -n 's/^OSINT_DATA_DIR=//p' .env 2>/dev/null)
OSINT_DATA_DIR := $(if $(strip $(OSINT_DATA_DIR)),$(OSINT_DATA_DIR),./data)

.PHONY: start stop off up down down-soft logs data-size data-prune data-reset labels panel baselines coverage

start:  ## Start the full local app (Docker stores + backend + frontend)
	@bash scripts/dev-up.sh

stop:  ## Stop the full local app (frontend + backend + Docker stores; keeps data)
	@bash scripts/dev-down.sh

down-soft: stop  ## Alias for a no-teardown stop
	@:

off: stop  ## Stop the app, then quit Docker Desktop on macOS
	@bash scripts/dev-off.sh

up: start  ## Alias for make start

down:  ## Fully stop and teardown docker runtime (data preserved in $OSINT_DATA_DIR)
	@bash scripts/dev-down.sh
	@if docker info >/dev/null 2>&1; then \
		docker compose down --timeout 5 >/dev/null; \
	else \
		echo "Docker is not reachable; store containers are already stopped." ; \
	fi

logs:  ## Tail background app logs (Ctrl-C to stop tailing; stack keeps running)
	@tail -n 40 -F logs/*.log

data-size:  ## Show disk used by each data subfolder
	@du -sh $(OSINT_DATA_DIR)/* 2>/dev/null || echo "no data yet at $(OSINT_DATA_DIR)"

data-prune:  ## Run retention housekeeping now
	.venv/bin/python scripts/prune_now.py

labels:  ## Compute P1-P3 ground-truth labels from ACLED aggregates (idempotent)
	.venv/bin/python -m app.labels.run

panel:  ## Export the country-month panel dataset (parquet + csv + meta)
	.venv/bin/python -m app.panel.run

baselines:  ## Score B0/B1/B2 baselines on the panel and write the report
	.venv/bin/python -m app.baselines.run

coverage:  ## Compute the WS-D coverage-bias table from ACLED aggregates
	.venv/bin/python -m app.coverage.run

data-reset:  ## Stop stack and wipe all local data (DESTRUCTIVE)
	@test -n "$(strip $(OSINT_DATA_DIR))" || { echo "OSINT_DATA_DIR is empty — refusing to delete"; exit 1; }
	docker compose down
	rm -rf $(OSINT_DATA_DIR)
	@echo "wiped $(OSINT_DATA_DIR)"
