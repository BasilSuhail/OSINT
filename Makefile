# Local data management. OSINT_DATA_DIR defaults to ./data (see .env).
# Resolve OSINT_DATA_DIR: explicit env > .env file > ./data default.
OSINT_DATA_DIR ?= $(shell sed -n 's/^OSINT_DATA_DIR=//p' .env 2>/dev/null)
OSINT_DATA_DIR := $(if $(strip $(OSINT_DATA_DIR)),$(OSINT_DATA_DIR),./data)

.PHONY: help env env-check fetch news news-all ask logs severity-grade severity-audit severity-agreement severity-bench category-audit category-agreement within-eval up share down clear start stop off up-docker down-docker docker-prune clean-dev down-soft data-size data-prune data-reset labels panel baselines coverage journal stories stories-audit backfill-signals brain enrich

#: How the analysis commands below run Python.
#:
#: A host virtual environment when there is one — a developer with `.venv` gets
#: the fast path and their own interpreter. Otherwise the worker container, which
#: every install has, because `make up` built it.
#:
#: Before this, all twenty-nine of them called `.venv/bin/python` outright, so on
#: a fresh clone every one failed: nothing creates a host virtualenv, the backend
#: runs in a container, and `make stories` — documented as the way to build the
#: story clusters — could not work on a machine that had only ever followed the
#: README. The workaround was `docker compose exec` typed out by hand, which is
#: what this variable now does for you.
#:
#: The container path needs the stack up. `make up` first if a command reports no
#: such service.
RUN_PY ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; \
	else echo "docker compose exec -T worker python"; fi)

#: Bare `make` starts the app, which is what it has always done. Stated rather
#: than inherited from whichever target happens to be written first — adding a
#: command at the top of this file should not change what `make` on its own
#: means.
.DEFAULT_GOAL := up

help:  ## List every command in this file, with what it does
	@grep -hE '^[a-z][a-z0-9_-]*:.*##' $(MAKEFILE_LIST) \
		| sed -e 's/:.*##/\t/' \
		| sort \
		| awk -F'\t' '{printf "  %-16s %s\n", $$1, $$2}'

# ── The three commands ──────────────────────────────────────────────────────
# Everything else below is either an alias kept for muscle memory or a
# single-purpose analysis task.

env:  ## Create .env, add missing keys, and fill in what nobody should have to type
	@python3 scripts/env_setup.py sync

env-refresh:  ## Re-derive the address settings for this machine. Secrets untouched
	@python3 scripts/env_setup.py refresh

env-check:  ## Say what .env is missing, empty or has typed wrong
	@python3 scripts/env_setup.py check || \
		echo "  (that is the report, not a crash — nothing above stops \`make up\`)"

up:  ## Start everything: Docker stores, backend, frontend, Ollama
	@bash scripts/dev-up.sh

share:  ## Start everything, reachable from the local network (no password)
	@LAN_SHARE=1 bash scripts/dev-up.sh

down:  ## Stop everything, keep all data
	@bash scripts/dev-down.sh

clear:  ## Remove regenerable junk: build caches, __pycache__, logs, Docker cruft
	@bash scripts/dev-clear.sh

# ── Aliases (same behaviour, older names) ───────────────────────────────────
start: up  ## Alias for make up
	@:

stop: down  ## Alias for make down
	@:

down-soft: down  ## Alias for make down
	@:

clean-dev: clear  ## Alias for make clear
	@:

off:  ## Stop everything, then quit Docker Desktop on macOS
	@bash scripts/dev-off.sh

# ── Containerised backend (#530, unified into `make up` by #634) ────────────
# There is now ONE way to run the app: `make up` runs stores, api, worker,
# worker-analytics and beat in containers, with Ollama and the frontend on the
# host. Two paths meant two things to keep correct, and they diverged — the
# compose worker carried no `-Q`, so nothing consumed the `analytics` queue and
# every heavy job was published to a queue with no consumer.

up-docker: up  ## Alias for make up (kept so older docs and habits still work)
	@:

down-docker:  ## Stop the containerised backend, leaving stores and data alone
	@docker compose --profile app stop migrate api worker worker-analytics beat >/dev/null 2>&1 || true
	@docker compose --profile app rm -f migrate api worker worker-analytics beat >/dev/null 2>&1 || true
	@echo "Containerised backend stopped. Stores still running; data untouched."

docker-prune: clear  ## Alias for make clear
	@:

logs:  ## Tail the whole stack — backend containers + host frontend (Ctrl-C stops tailing only)
	@bash scripts/dev-logs.sh

fetch:  ## Fetch from every source now, instead of waiting for the schedule (#993)
	@docker compose exec -T worker python -m app.ingest.fetch_now $(SOURCES)

news:  ## Build the stories, cards and written summary — a few minutes (#997)
	@docker compose exec -T worker python -m app.news_now

ask:  ## Ask from the terminal, with the real error instead of "offline" (#997)
	@docker compose exec -T api python -m app.brain.ask_now $(Q)

news-all:  ## Same, but gist every story in the window rather than a batch — hours (#997)
	@docker compose exec -T worker python -m app.news_now --all

#: `du` exits non-zero when it cannot descend into a directory, and it cannot
#: descend into `data/postgres` — that belongs to the database image's own user.
#: So `|| echo "no data yet"` fired on a populated directory and printed the
#: denial as an absence, directly underneath the sizes it had just listed. It also
#: reported 4 KB for Postgres: the directory entry, not the database.
#:
#: Emptiness is decided by looking now, and `sudo` is named because the number
#: that matters most is the one an unprivileged `du` cannot see.
data-size:  ## Show disk used by each data subfolder
	@if [ -d "$(OSINT_DATA_DIR)" ] && [ -n "$$(ls -A "$(OSINT_DATA_DIR)" 2>/dev/null)" ]; then \
		du -sh "$(OSINT_DATA_DIR)"/* 2>/dev/null || true; \
		echo "  (sudo for the true Postgres size — its files are not readable by you)"; \
	else \
		echo "no data yet at $(OSINT_DATA_DIR)"; \
	fi

data-prune:  ## Run retention housekeeping now
	$(RUN_PY) -m app.prune_now

labels:  ## Compute P1-P3 ground-truth labels from ACLED aggregates (idempotent)
	$(RUN_PY) -m app.labels.run

panel:  ## Export the country-month panel dataset (parquet + csv + meta)
	$(RUN_PY) -m app.panel.run

baselines:  ## Score B0/B1/B2 baselines on the panel and write the report
	$(RUN_PY) -m app.baselines.run

coverage:  ## Compute the WS-D coverage-bias table from ACLED aggregates
	$(RUN_PY) -m app.coverage.run

journal:  ## Run the WS-E prediction journal once (emit + grade + scoreboard)
	$(RUN_PY) -m app.journal.run

stories:  ## Cluster the rolling news window into stories (WS-A)
	$(RUN_PY) -m app.stories.run

stories-audit:  ## Emit the threshold hand-check sheet (WS-C step 1, #334)
	$(RUN_PY) -m app.stories.audit

sensor-checks:  ## Run WS-C sensor cross-checks once — claim-vs-sensor verdicts (#361)
	$(RUN_PY) -m app.corroboration.run

disagreement:  ## Run WS-B telling divergence once — most contested stories (#370)
	$(RUN_PY) -m app.disagreement.run

indicator-ranking:  ## Rank every dashboard indicator by measured predictive value (WS-F, #376)
	$(RUN_PY) -m app.ranking.run

onset-eval:  ## Run the pre-registered onset evaluation — the composite's real exam (#380)
	$(RUN_PY) -m app.onset.run

within-eval:  ## Run the pre-registered within-country evaluation (#582)
	$(RUN_PY) -m app.within.run

severity-grade:  ## Grade stored news severity with the local model — reports; --apply writes (#591)
	$(RUN_PY) -m app.severity.grade_run

severity-audit:  ## Emit the human-check sheet that gates LLM severity use (#593)
	$(RUN_PY) -m app.severity.audit

severity-agreement:  ## Publish model-vs-human agreement from the filled sheet (#593)
	$(RUN_PY) -m app.severity.agreement

severity-bench:  ## Replay the human sheet through candidate graders (#646)
	$(RUN_PY) -m app.severity.bench

validator:  ## Run WS-G local-LLM claim extraction once (needs Ollama, #378)
	$(RUN_PY) -m app.validator.run

brain:  ## Run the brain narrate once — needs Ollama + llama3.2:3b (#409)
	$(RUN_PY) -m app.brain.run

category-audit:  ## Emit the blank sheet that gates a categoriser change (#951)
	$(RUN_PY) -m app.brain.category_audit

category-agreement:  ## Score models against the filled category sheet (#951)
	$(RUN_PY) -m app.brain.category_agreement

enrich:  ## Run one brain enrichment pass — gist + tags for new stories (#413)
	$(RUN_PY) -m app.brain.enrich_run

brain-qa-eval:  ## Compare Q&A candidate models locally (Phase C, #413)
	$(RUN_PY) -m app.brain.qa_eval

brain-qa-audit:  ## Emit the human answer-audit sheet (#413 item 9)
	$(RUN_PY) -m app.brain.qa_audit

brain-qa-audit-score:  ## Score a graded answer-audit sheet
	$(RUN_PY) -m app.brain.qa_audit score

validator-audit:  ## Emit the ~50-story human-check sheet for the validator (#378)
	$(RUN_PY) -m app.validator.audit

validator-agreement:  ## Compute + publish the model-vs-human agreement rate from the filled sheet (#386)
	$(RUN_PY) -m app.validator.agreement

briefing:  ## Generate the weekly briefing now — the newsletter artifact (#401)
	$(RUN_PY) -m app.briefing.run

data-audit:  ## Run the source-data audit now and record it in the run history (#669)
	$(RUN_PY) -m app.audit.task

backfill-signals:  ## Backfill historical market+geopolitical+hazard composite scores (2015-2024); GDELT download resumes via $OSINT_DATA_DIR/gdelt/ checkpoints
	$(RUN_PY) -m app.composite.backfill

data-reset:  ## Stop stack and wipe all local data (DESTRUCTIVE)
	@test -n "$(strip $(OSINT_DATA_DIR))" || { echo "OSINT_DATA_DIR is empty — refusing to delete"; exit 1; }
	docker compose down
	rm -rf $(OSINT_DATA_DIR)
	@echo "wiped $(OSINT_DATA_DIR)"
