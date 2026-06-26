# Local data management. OSINT_DATA_DIR defaults to ./data (see .env).
OSINT_DATA_DIR ?= ./data

.PHONY: data-size data-prune data-reset

data-size:  ## Show disk used by each data subfolder
	@du -sh $(OSINT_DATA_DIR)/* 2>/dev/null || echo "no data yet at $(OSINT_DATA_DIR)"

data-prune:  ## Run retention housekeeping now
	.venv/bin/python scripts/prune_now.py

data-reset:  ## Stop stack and wipe all local data (DESTRUCTIVE)
	docker compose down
	rm -rf $(OSINT_DATA_DIR)
	@echo "wiped $(OSINT_DATA_DIR)"
