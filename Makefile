# Local data management. OSINT_DATA_DIR defaults to ./data (see .env).
# Resolve OSINT_DATA_DIR: explicit env > .env file > ./data default.
OSINT_DATA_DIR ?= $(shell sed -n 's/^OSINT_DATA_DIR=//p' .env 2>/dev/null)
OSINT_DATA_DIR := $(if $(strip $(OSINT_DATA_DIR)),$(OSINT_DATA_DIR),./data)

.PHONY: start stop off up down down-soft clean-dev logs data-size data-prune data-reset labels panel baselines coverage journal stories stories-audit backfill-signals brain enrich

start:  ## Start the full local app (Docker stores + backend + frontend)
	@bash scripts/dev-up.sh

stop:  ## Stop the full local app (frontend + backend + Docker stores; keeps data)
	@bash scripts/dev-down.sh

down-soft: stop  ## Alias for a no-teardown stop
	@:

off: stop  ## Stop the app, then quit Docker Desktop on macOS
	@bash scripts/dev-off.sh

clean-dev:  ## Stop stale frontend/build processes and clear generated Next cache
	@bash scripts/dev-clean.sh

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

journal:  ## Run the WS-E prediction journal once (emit + grade + scoreboard)
	.venv/bin/python -m app.journal.run

stories:  ## Cluster the rolling news window into stories (WS-A)
	.venv/bin/python -m app.stories.run

stories-audit:  ## Emit the threshold hand-check sheet (WS-C step 1, #334)
	.venv/bin/python -m app.stories.audit

sensor-checks:  ## Run WS-C sensor cross-checks once — claim-vs-sensor verdicts (#361)
	.venv/bin/python -m app.corroboration.run

disagreement:  ## Run WS-B telling divergence once — most contested stories (#370)
	.venv/bin/python -m app.disagreement.run

indicator-ranking:  ## Rank every dashboard indicator by measured predictive value (WS-F, #376)
	.venv/bin/python -m app.ranking.run

onset-eval:  ## Run the pre-registered onset evaluation — the composite's real exam (#380)
	.venv/bin/python -m app.onset.run

validator:  ## Run WS-G local-LLM claim extraction once (needs Ollama, #378)
	.venv/bin/python -m app.validator.run

brain:  ## Run the brain narrate once — needs Ollama + qwen2.5:1.5b (#409)
	.venv/bin/python -m app.brain.run

enrich:  ## Run one brain enrichment pass — gist + tags for new stories (#413)
	.venv/bin/python -m app.brain.enrich_run

brain-qa-eval:  ## Compare Q&A candidate models locally (Phase C, #413)
	.venv/bin/python -m app.brain.qa_eval

brain-qa-audit:  ## Emit the human answer-audit sheet (#413 item 9)
	.venv/bin/python -m app.brain.qa_audit

brain-qa-audit-score:  ## Score a graded answer-audit sheet
	.venv/bin/python -m app.brain.qa_audit score

validator-audit:  ## Emit the ~50-story human-check sheet for the validator (#378)
	.venv/bin/python -m app.validator.audit

validator-agreement:  ## Compute + publish the model-vs-human agreement rate from the filled sheet (#386)
	.venv/bin/python -m app.validator.agreement

briefing:  ## Generate the weekly briefing now — the newsletter artifact (#401)
	.venv/bin/python -m app.briefing.run

backfill-signals:  ## Backfill historical market+geopolitical+hazard composite scores (2015-2024); GDELT download resumes via $OSINT_DATA_DIR/gdelt/ checkpoints
	.venv/bin/python -m app.composite.backfill

data-reset:  ## Stop stack and wipe all local data (DESTRUCTIVE)
	@test -n "$(strip $(OSINT_DATA_DIR))" || { echo "OSINT_DATA_DIR is empty — refusing to delete"; exit 1; }
	docker compose down
	rm -rf $(OSINT_DATA_DIR)
	@echo "wiped $(OSINT_DATA_DIR)"
