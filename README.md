# OSINT World Monitor

[![backend](https://github.com/BasilSuhail/OSINT/actions/workflows/backend.yml/badge.svg)](https://github.com/BasilSuhail/OSINT/actions/workflows/backend.yml)
[![frontend](https://github.com/BasilSuhail/OSINT/actions/workflows/frontend.yml/badge.svg)](https://github.com/BasilSuhail/OSINT/actions/workflows/frontend.yml)
[![CodeQL](https://github.com/BasilSuhail/OSINT/actions/workflows/codeql.yml/badge.svg)](https://github.com/BasilSuhail/OSINT/actions/workflows/codeql.yml)
[![dependency review](https://github.com/BasilSuhail/OSINT/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/BasilSuhail/OSINT/actions/workflows/dependency-review.yml)
[![licence: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/licence-PolyForm%20Noncommercial%201.0.0-blue)](LICENSE)

**A self-hosted world-event monitor that shows its evidence — and publishes the
experiments where its own predictions failed.**

It collects public data about world events — news, machine-coded event records,
disasters, markets, cyber indicators, satellite fire detections, aircraft
presence — normalises it into one row shape, stores it locally, and puts it on a
map with the provenance attached. It runs on one machine. Nothing leaves it.

<br>

[![Read the handbook](https://img.shields.io/badge/READ_THE_HANDBOOK-1f6feb?style=for-the-badge&logo=readthedocs&logoColor=white)](HANDBOOK.md)
&nbsp;
[![Quick start](https://img.shields.io/badge/QUICK_START-238636?style=for-the-badge&logo=docker&logoColor=white)](#quick-start)
&nbsp;
[![What failed](https://img.shields.io/badge/WHAT_FAILED-8957e5?style=for-the-badge)](#02-the-claim-it-was-built-to-test)

<br>

![The console: story feed, world map, and filter rail](images/console-screenshot-live.jpg)

## See it without installing anything

**[basilsuhail.github.io/OSINT](https://basilsuhail.github.io/OSINT/)** — the map,
the filters and the cards, drawn from a frozen snapshot of a running console.
Hazards, military aircraft and AIS vessels, all clickable. Nothing there is
live: it is one moment saved to a file, and the page says so at the top and
again beside anything it had to thin out.

Everything below is how to run the real thing, which fetches, stores, scores
and refreshes on your own machine.

## Quick start

Six steps, in order. Skip step 1 if you already run Docker and current Node.

### Step 1 — Docker and Node

Pick your system. Each block is one paste.

<details open>
<summary><b>Linux</b> — Debian, Ubuntu, Raspberry Pi OS</summary>

```bash
sudo apt update && sudo apt install -y git curl ca-certificates && \
curl -fsSL https://get.docker.com | sudo sh && \
sudo usermod -aG docker "$USER" && \
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && \
sudo apt install -y nodejs && sudo corepack enable
```

**Then log out and back in.** Group membership is read at login, so `docker` will
not work in the shell that just added you to the group — and it fails by saying
the daemon is unreachable, which reads as "Docker is not installed".

</details>

<details>
<summary><b>macOS</b> — needs <a href="https://brew.sh">Homebrew</a></summary>

```bash
brew install git node && brew install --cask docker && sudo corepack enable && open -a Docker
```

Wait for the Docker whale in the menu bar to stop animating before step 4.

</details>

<details>
<summary><b>Windows</b> — via WSL2</summary>

In PowerShell **as administrator**:

```powershell
wsl --install -d Ubuntu
```

Reboot, then install [Docker Desktop](https://docs.docker.com/desktop/install/windows-install/)
and turn on **Settings → Resources → WSL Integration** for Ubuntu.

Everything after this runs **inside the Ubuntu terminal**, not PowerShell:

```bash
sudo apt update && sudo apt install -y git curl ca-certificates && \
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && \
sudo apt install -y nodejs && sudo corepack enable
```

No `get.docker.com` here — Docker Desktop supplies the engine through WSL
integration, and installing a second one inside Ubuntu fights it.

</details>

**Do not install pnpm by name.** `corepack enable` fetches the version
`packageManager` pins. `npm install -g pnpm` or `corepack prepare pnpm@latest`
gets a different one that resolves the lockfile differently, and it surfaces
later as a build failure that looks nothing like a version mismatch.

### Step 2 — Ollama

Called optional, and everything else runs without it. But without it the **Ask
panel answers nothing**: ask it any question and it replies `The brain is offline
right now.`, and the written situation summaries never appear. The map, the feed,
ingestion, the scores and the audit trail are unaffected.

```bash
curl -fsSL https://ollama.com/install.sh | sh     # Linux, and WSL2 Ubuntu
brew install ollama && ollama serve               # macOS
```

### Step 3 — the models

Nothing to do. `make up` pulls them in step 5.

There are **three, about 5 GB in total** — one writes the situation summary, one
answers in the Ask panel, one builds the embeddings behind search. Only one is
loaded at a time, so three on disk is not three in memory. Pull them ahead of
time if you would rather get the download out of the way:

```bash
ollama pull llama3.2:3b
ollama pull qwen3.5:4b-q4_K_M
ollama pull nomic-embed-text
```

Install Ollama later and re-run `make up` and it pulls them then. Nothing else
needs redoing.

### Step 4 — get the code

```bash
git clone https://github.com/BasilSuhail/OSINT.git
cd OSINT
```

### Step 5 — settings, then start

```bash
make env
make up
```

`make env` writes `.env` and fills it in — database password, API token, the
addresses this machine answers to. **Nothing needs typing into it.** It never
overwrites a value you have set, so it is safe to re-run any time.

`make up` brings up Postgres, Redis, migrations, the API, the workers, the
console, and Ollama if it is installed. First run takes 20–40 minutes: container
images, browser packages, then the models.

Open <http://localhost:3000>.

To reach it from your phone or another computer instead:

```bash
make share
```

That prints a URL to hand over. It is open to everyone on your network with no
password — `make up` closes it again.

Stop everything, keeping all data:

```bash
make down
```

### Step 6 — data

**The console is empty at first, and that is not a fault.** Nothing has been
fetched yet. The schedule collects markets every five minutes and news on the
quarter-hour, so the first rows land one to fifteen minutes in, and it fills out
over the following hours.

Leave it running and it populates itself. To fill it now:

```bash
make fetch                        # every source, once
make news                         # then build the stories and the summary
```

`make fetch` fills the **map** — events, hazards, aircraft, markets. It prints
what each source returned, and which are dormant for want of an API key; on
screen "no data from this source" and "this source needs a key" look identical.

`make news` fills the **left-hand side** — the story feed and the written
situation summary. Those are built from the news `make fetch` collected, so run
it second.

Just one source, when you know which:

```bash
make fetch SOURCES="gdelt gdacs"
```

**The two halves fill at different speeds on their own.** The map arrives within
minutes; the situation card needs clustering to finish before the summary can be
written from it, so left to the schedule that is up to 45 minutes. A full map
beside "No stories in the window yet" is that gap, not a fault.

---

`make help` lists every command with a line saying what it does. Optional source
keys and moving the data directory: [§5](HANDBOOK.md#5-configure-it-safely).

## Updating, and running a branch

Pull the latest:

```bash
git checkout main
git pull
make env                  # adds any settings the update introduced
make up
```

Try a branch — a fix you want to test before it merges, say:

```bash
git fetch origin
git checkout <branch-name>
git pull
make env
make up
```

Back to `main` afterwards with the first block. `make down` first if the stack
is running and the branch changes how it starts.

**`make env` after every pull is the step people skip.** New settings arrive in
`env.example` over time and this is how they reach your file; miss it and the
feature they switch on stays quietly off, with nothing saying so. It never
touches a value you have already set. `make up` runs the check and tells you
what it found, then starts anyway.

Full prerequisites: [§3](HANDBOOK.md#3-what-you-need-before-starting). The
walkthrough: [§1](HANDBOOK.md#1-start-here-download-install-run-and-stop).
Anything that goes wrong: [§19](HANDBOOK.md#19-troubleshooting).

> **Read [§0](#0-what-this-system-is-for-and-what-it-is-not) before trusting any
> number on the screen.** The predictive claim this project was built to test has
> been put through every pre-registered protocol built for it and refused every time. That is stated up front, with
> the tables, rather than buried.

**Licence: PolyForm Noncommercial 1.0.0 — source-available, not open source.**
Security reporting, provider data terms, and attribution are in
[§25](#25-licence-security-and-provider-terms).

## 📖 The full technical handbook

> ### **[→ Open HANDBOOK.md](HANDBOOK.md)**
>
> **4,300 lines. 24 sections. Everything underneath this page.**

|  | The handbook covers |
| --- | --- |
| **Operate it** | [Install and first run](HANDBOOK.md#1-start-here-download-install-run-and-stop) · [read the console](HANDBOOK.md#2-see-and-understand-the-console) · [configure](HANDBOOK.md#5-configure-it-safely) · [every control](HANDBOOK.md#7-use-the-console) · [troubleshooting](HANDBOOK.md#19-troubleshooting) |
| **Every formula** | [Corroboration](HANDBOOK.md#142-corroboration--how-much-independent-telling-a-story-has) · [divergence](HANDBOOK.md#143-divergence--how-differently-two-country-blocs-word-the-same-story) · [the composite](HANDBOOK.md#144-the-composite-stress-index--and-why-the-live-one-reads-05) · [severity](HANDBOOK.md#145-severity--and-why-08-does-not-compare-across-families) · [lead-time gate](HANDBOOK.md#148-the-lead-time-gate--does-narrative-move-before-the-physical-signal) — each with a worked example and its failure modes |
| **What was tested, and what failed** | [Every pre-registered refusal](HANDBOOK.md#15-evaluation--what-was-claimed-what-was-tested-what-failed), with baselines, bootstrap confidence intervals, and the held-out window |
| **Whether to trust the data** | [Bias and provenance](HANDBOOK.md#16-bias-provenance-and-one-country-traced-end-to-end), including one country traced end to end with measured counts |
| **Rebuild it yourself** | [Every command](HANDBOOK.md#17-reproduce-the-analysis) that regenerates every number quoted anywhere |
| **Reference** | [Data sources](HANDBOOK.md#9-data-sources) · [pipeline](HANDBOOK.md#10-the-end-to-end-data-pipeline) · [storage](HANDBOOK.md#11-data-storage-and-retention) · [backend](HANDBOOK.md#12-backend-guide) · [frontend](HANDBOOK.md#13-frontend-guide) · [glossary](HANDBOOK.md#22-glossary) · [code walkthroughs](HANDBOOK.md#23-code-walkthroughs) |

[![the console, with every control numbered](images/console-guide.jpg)](HANDBOOK.md#21-real-interface-map)

*Every numbered control above is explained in
**[§2.1 of the handbook](HANDBOOK.md#21-real-interface-map)**, each with a link
to the code that produces it.*

## Contents

- [0. What this system is for, and what it is not](#0-what-this-system-is-for-and-what-it-is-not)
- [25. Licence, security, and provider terms](#25-licence-security-and-provider-terms)
- [26. Repository map](#26-repository-map)
- [27. Documentation index](#27-documentation-index)
- [28. SWOT](#28-swot)

> Section numbers are shared across both files and never reused: **1–24 are in
> [HANDBOOK.md](HANDBOOK.md)**, so a reference to §15 means the same thing
> wherever you read it.

---

# 0. What this system is for, and what it is not

Read this page first. It states the claim the project makes, the claim it does
**not** make, and what is actually being offered — so nothing later in the
handbook has to be inferred.

## 0.1 In one paragraph

This is a self-hosted system that collects public data about world events —
news, machine-coded event records, disasters, markets, cyber indicators,
satellite fire detections, aircraft presence — normalises it into one row shape,
stores it locally, and puts it on a map with the evidence attached. It runs on
one machine. Nothing leaves it. Every number it shows can be traced back to the
row that produced it.

## 0.2 The claim it was built to test

> A composite of several open-data signal domains discriminates later instability
> better than the best single-domain baseline.

That claim was pre-registered, evaluated, and **refused**. Not once — under every
protocol built for it, including on a held-out window reserved specifically for
the question:

| Evaluation | Result |
| --- | --- |
| Incidence, pooled | Composite AUROC ≈ 0.502 against a 0.929 base rate |
| Head-to-head vs single domains | `beaten: []` — dominates none of them, in either window |
| Held-out test 2023–24 | Same verdict on data reserved for this question |
| Onset | 0.496 / 0.520 / 0.526 — a coin flip |
| Within-country concordance | 0.531 best, CI [0.474, 0.582], below the declared 0.55 |

**The predictive claim failed.** This document does not soften that anywhere, and
§15 gives every table.

## 0.3 What is actually being offered

The composite failed. The machinery that caught it did not.

What this project delivers is an **apparatus for not fooling yourself**, built
around data that makes fooling yourself easy. Concretely:

- **Protocols are frozen before results exist.** Eligibility, target, horizons,
  contenders, metrics and the decision rule are written down and dated first. The
  run happens once. Corrections are amendments, never edits (§15.1).
- **Verdicts are computed, not narrated.** A threshold decides, in code. The
  within-country evaluation prints `NEGATIVE` because `_verdict()` said so, not because
  someone read the table and agreed (§15.7).
- **A trend that fails the rule is reported as a failure.** The composite rises
  monotonically with horizon. The protocol declared in advance that 0.50–0.55 is
  a negative rather than a promising trend, so it is recorded as a negative
  (§15.7).
- **Forecasts of a constant are refused entry.** 1,101 forecasts of the number
  0.5 were once recorded as forecasts. The check is now concentration, not exact
  flatness (§14.4).
- **A hindcast cannot enter the journal.** A "prediction" whose window overlaps
  the known past is skipped, because grading it would fake a track record (§15.10).
- **Independence must be positively established.** A source with no ownership
  record contributes nothing to a confidence score, because ten anonymous blogs
  are one claim told ten times, not ten confirmations (§14.6).
- **Absence is not imputed as average.** A missing domain is excluded and the
  weights renormalised, rather than entered as "exactly average" (§14.4).
- **The bias is measured and published**, including the finding that 54 of 55
  news feeds are English and that a country the system reports on can have no
  domestic feed at all (§16).

The evidence that this apparatus works is that **it caught its own author's
claim and refused it, repeatedly, on the record.** A system that only ever
confirms the hypothesis of the person who built it has not been tested. This one
has.

## 0.4 What it does not claim

- **It does not forecast instability.** See above. Any future claim requires a
  new pre-registered version and a new evaluation.
- **It does not calculate truth.** It shows provenance, corroboration,
  disagreement and sensor agreement. Six independent outlets can be
  independently wrong.
- **Its scores are not probabilities.** They are orderings. Nothing here is
  calibrated, so 0.875 does not mean "correct 87.5% of the time".
- **It does not see the whole world.** It sees what open, mostly English-language
  feeds publish, and it says so with numbers rather than a disclaimer.
- **It is not a safety-critical alerting service.** Upstream feeds fail, arrive
  late, change format, and withdraw access.

## 0.5 What is genuinely unfinished

Stated here rather than left to be discovered:

- **The running version has never been evaluated.** Everything in §15 grades
  `v1.0`. The live system emits `v3.0`, which changed the domain structure and
  the weights (§14.1).
- **There is no forward evidence yet.** 1,695 predictions issued, **0 graded**
  (§15.10).
- **Five of six declared robustness tests have not been run** (§15.9).
- **Two of the five label families were never built.** `P4` (market crisis) and
  `P5` (hazard disruption) do not exist, so a multi-modal index is currently
  graded only on whether it predicts conflict
  ([§15.2](HANDBOOK.md#152-what-counts-as-a-positive--the-ground-truth)).
- **The pre-specified case studies were never filled in.**
- **Reporting delay has never been measured on this system's own data** (§16.4).

## 0.6 Who this is useful to, and for what decision

It is useful to someone who has to answer *"is this story actually being
independently reported, or is it one wire item repeated?"*, *"does any physical
sensor agree with this claim?"*, *"are two countries telling this differently?"*,
and *"how much should I trust what I am looking at?"* — and who wants each answer
to arrive with the evidence attached rather than as a verdict.

It is not useful to someone who wants a risk number to act on. That number was
built, tested, and found not to work.

## 0.7 Where to go next

| If you want to | Read |
| --- | --- |
| Run it | [§1](HANDBOOK.md#1-start-here-download-install-run-and-stop) |
| Understand the screen | [§2](HANDBOOK.md#2-see-and-understand-the-console) |
| See how a number is computed | [§14](HANDBOOK.md#14-methods--every-number-the-system-publishes) |
| See what was tested and what failed | [§15](HANDBOOK.md#15-evaluation--what-was-claimed-what-was-tested-what-failed) |
| Judge the data before trusting it | [§16](HANDBOOK.md#16-bias-provenance-and-one-country-traced-end-to-end) |
| Rebuild every number yourself | [§17](HANDBOOK.md#17-reproduce-the-analysis) |
| Find any file in the repository | [§26](#26-repository-map) |
| Find the right document in `docs/` | [§27](#27-documentation-index) |
| Know the licence, security policy, and data terms | [§25](#25-licence-security-and-provider-terms) |
| See a candid read of where this stands | [§28](#28-swot) |

---

# 25. Licence, security, and provider terms

## 25.1 Licence

**PolyForm Noncommercial 1.0.0.** Full text in
[`LICENSE`](https://github.com/BasilSuhail/OSINT/blob/main/LICENSE).

**This is source-available, not open source.** The distinction is not pedantry:
every OSI-approved licence permits commercial use, so calling this open source
would tell you that you have a right you do not have.

You may use it, run it, study it, fork it, modify it and share your changes, for
any **noncommercial** purpose — personal projects, study and research, and use by
charities, educational institutions, public research bodies and government. You
may not sell it or use it commercially.

Two reasons, and the second is the real one:

- **It is under development and its outputs have been wrong before.** The
  composite is a coin flip in every pre-registered evaluation, and that is written
  down in [§15](HANDBOOK.md#15-evaluation--what-was-claimed-what-was-tested-what-failed)
  rather than hidden. Nothing here is fit to sell.
- **It ingests third-party feeds.** Several are free for noncommercial or
  research use and require a separate agreement for anything else. Those terms
  are not the maintainer's to hand on, so they are not handed on.

## 25.2 The data is not covered by that licence

The licence covers the code in this repository and nothing else. It does not
cover, and cannot cover, the data this software fetches. Those feeds belong to
the organisations that publish them, each on its own terms. Nobody here has the
right to sub-licence them, so nobody here has granted you anything over them.

> **Running this software makes you the one fetching the data.** Whatever the
> provider requires — registration, an API key, attribution, a commercial
> licence, a limit on redistribution — it requires of *you*, directly, under the
> agreement you accept when you take the key.

[`NOTICE.md`](https://github.com/BasilSuhail/OSINT/blob/main/NOTICE.md) is the
maintained index of every feed and where its terms live. It is a pointer, not a
legal summary and not legal advice. Terms change. Read the current ones for any
feed you actually enable. Operational guidance on this is in
[§9.5](HANDBOOK.md#95-source-terms-and-attribution).

## 25.3 Third-party attribution

The bundled gazetteer files under
[`app/enrichment/data/`](https://github.com/BasilSuhail/OSINT/tree/main/app/enrichment/data)
are **Natural Earth**, which is public domain.

Base map tiles, imagery overlays and aircraft presence are fetched by the
browser directly from their publishers and are never stored; their attribution
is rendered on the map itself.

## 25.4 Reporting a security problem

Report privately — **do not open a public issue**. The channels, the information
to include, and the automated tooling in place are in
[`SECURITY.md`](https://github.com/BasilSuhail/OSINT/blob/main/SECURITY.md).

What runs continuously on this repository:

| Control | What it covers |
| --- | --- |
| Dependabot | `pip` and `pnpm` dependencies, weekly, opens update PRs |
| CodeQL | push, pull request, and a weekly scheduled scan |
| `pip-audit` | backend dependencies, in the `backend` workflow |
| `pnpm audit --audit-level high` | frontend dependencies, in the `frontend` workflow |
| Dependency review | blocks high-severity dependency regressions on PRs |
| Secret scanning + push protection | enabled at repository level |

The repository-level security baseline, what is enabled and what hardening is
still recommended, is logged in
[`docs/security.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/security.md).

**Operational security when you run it** is a separate matter and is covered in
this handbook: the API token in [§5.4](HANDBOOK.md#54-protect-the-api-outside-one-laptop),
and network exposure — including the fact that `make share` adds **no password**
— in [§5.7](HANDBOOK.md#57-make-share--opening-the-console-to-the-local-network).

## 25.5 Working agreements

This repository is public and has been forked; forks copy the full history.
Anything committed is beyond recall the moment it is pushed. The rules for what
may and may not go into a commit, an issue or a pull request are in
[`AGENTS.md`](https://github.com/BasilSuhail/OSINT/blob/main/AGENTS.md), which is
read by both people and coding agents.

The short version: no personal names, no contact details, no credentials, and
one issue → one branch → one pull request → one commit. A pre-commit hook screens
staged files and blocks on a hit; a block is a prompt to rephrase, not an
obstacle to route around.

## 25.6 Contributing, and reporting things that are not security issues

**Issues are welcome.** A good one names what you ran, what you expected, and
what happened, with the relevant lines from `bash scripts/dev-logs.sh`. If the
console is involved, say which browser. [§19](HANDBOOK.md#19-troubleshooting)
covers the failures that already have known causes — worth a look first, because
several of them look like bugs and are configuration.

**Security problems do not go in issues.** Use the private channel in
[§25.4](#254-reporting-a-security-problem).

**Pull requests**: one issue, one branch, one pull request, one commit. Read
[`AGENTS.md`](https://github.com/BasilSuhail/OSINT/blob/main/AGENTS.md) first —
it is short, and it is binding on what may appear in a commit message, an issue
or a PR description, because this repository is public and has been forked.

Before opening one:

```bash
make verify        # or: ruff check . && ruff format --check . && pytest
cd osint-frontend && pnpm exec tsc --noEmit && pnpm exec vitest run
```

A pre-commit hook screens staged files and blocks on a hit. A block is a prompt
to rephrase, not an obstacle to route around.

**What is most useful right now**, in order: an evaluation of the running
`v3.0` composite ([§14.1](HANDBOOK.md#141-what-fixed-before-running-means-in-this-repository)),
any of the five unrun robustness tests
([§15.9](HANDBOOK.md#159-sensitivity-and-robustness--declared-and-honestly-incomplete)),
a chance-corrected agreement statistic for the severity grader
([§14.5](HANDBOOK.md#145-severity--and-why-08-does-not-compare-across-families)),
and non-English or non-Anglophone-origin feeds
([§16.2](HANDBOOK.md#162-the-news-feed-registry-measured)).

---

# 26. Repository map

The shape first, then the route data takes through it.

```text
OSINT/
├── app/                      PYTHON BACKEND — ingest · score · serve
│   ├── api.py                  FastAPI read-API: /events /scores /ingest-health /stream
│   ├── celery_app.py           Celery app instance (broker = Redis)
│   ├── tasks.py                Celery tasks + beat schedule (cadence + nightly prune)
│   ├── fetcher_registry.py     maps source name → fetcher
│   ├── persistence.py          upsert events into Postgres (+ Redis "new rows" tick)
│   ├── events_bus.py           Redis pub/sub channel powering the live SSE stream
│   ├── housekeeping.py         retention policy (see RETENTION_* in .env)
│   ├── db.py / db_models.py    SQLAlchemy engine/session + table definitions
│   ├── settings.py             ALL config, read from .env
│   ├── models.py               canonical Event/Score shapes
│   ├── watchdog.py             ingest health monitor
│   ├── sources/                one fetcher per feed + rss_feeds.json registry
│   ├── composite/              aggregation · normalisation · scoring · backfill
│   ├── corroboration/          per-story confidence + sensor cross-checks
│   ├── disagreement/           cross-country telling divergence
│   ├── divergence/             physical-vs-narrative spike and lead-time gate
│   ├── cii/                    Country Instability Index
│   ├── journal/                immutable prediction journal
│   ├── onset/ within/ baselines/  the pre-registered evaluations
│   ├── audit/                  nightly source-data audit + expectations
│   ├── brain/                  local-model narrate · enrich · ask
│   ├── severity/               grading and measured agreement
│   ├── devx/                   lan_share — who on the network may reach this
│   └── enrichment/             geocode · NER · sentiment (+ data/ gazetteers)
│
├── osint-frontend/           NEXT.JS CONSOLE — reads app/api.py
│   ├── app/                    routes: page.tsx, layout.tsx, providers.tsx, news/
│   ├── lib/                    apiClient.ts · queries.ts · realtime.ts · types.ts
│   ├── components/             MapPane · CardDeck · FilterRail · panels/
│   ├── stores/                 zustand filter + selection stores
│   └── __tests__/              frontend suite
│
├── data/        ALL LOCAL STORAGE ($OSINT_DATA_DIR, gitignored)
│   ├── postgres/                the actual database files
│   ├── redis/                   Redis append-only file
│   ├── private/                 licensed/manual inputs — never commit
│   └── exports/                 generated reports (evaluations, audits)
├── backups/     snapshot dumps (gitignored)
├── migrations/  Alembic schema migrations
├── scripts/     dev-up.sh · dev-down.sh · snapshot.py · one-off tools
├── tests/       pytest suite (backend)
├── docs/        specifications, protocols, and evaluation records — see §27
│
├── docker-compose.yml   Postgres + Redis services
├── Makefile             every command in this handbook
├── env.example          copy → .env, then fill in
└── .env                 YOUR config and secrets (gitignored — never commit)
```

## 26.1 Where is…?

| I want | Open |
| --- | --- |
| My config and secrets | `.env`, from [`env.example`](https://github.com/BasilSuhail/OSINT/blob/main/env.example); read via [`app/settings.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/settings.py). Every setting explained in [§5](HANDBOOK.md#5-configure-it-safely) |
| The database itself | `data/postgres/` — relocate with `OSINT_DATA_DIR` ([§5.5](HANDBOOK.md#55-move-persistent-data-to-another-disk)) |
| What the console fetches | [`osint-frontend/lib/apiClient.ts`](https://github.com/BasilSuhail/OSINT/blob/main/osint-frontend/lib/apiClient.ts) ↔ served by [`app/api.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/api.py) |
| To add or adjust a source | [`app/sources/`](https://github.com/BasilSuhail/OSINT/tree/main/app/sources) + [`app/fetcher_registry.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/fetcher_registry.py) — full steps in [§12.5](HANDBOOK.md#125-add-or-change-a-source) |
| How long data is kept | [`app/housekeeping.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/housekeeping.py) and `RETENTION_*` ([§11.3](HANDBOOK.md#113-retention-rule)) |

## 26.2 Trace one row, source to screen

A GDELT event's whole life. Every path is a link.

| # | Stage | File | What happens |
| ---: | --- | --- | --- |
| 1 | fetch | [`app/sources/gdelt_fetcher.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/sources/gdelt_fetcher.py) | request the newest export |
| 2 | register | [`app/fetcher_registry.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/fetcher_registry.py) | name → fetcher lookup |
| 3 | schedule | [`app/tasks.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/tasks.py) | Celery Beat fires it on cadence |
| 4 | dedup + store | [`app/persistence.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/persistence.py) | upsert on stable identity → `events` |
| 5 | normalise | [`app/composite/normalization.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/composite/normalization.py) | rolling within-country z-score ([§14.4](HANDBOOK.md#144-the-composite-stress-index--and-why-the-live-one-reads-05)) |
| 6 | score | [`app/composite/scoring.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/composite/scoring.py) | weighted z → sigmoid → `scores` |
| 7 | serve | [`app/api.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/api.py) | `/events`, `/scores`, SSE stream |
| 8 | fetch in browser | [`osint-frontend/lib/apiClient.ts`](https://github.com/BasilSuhail/OSINT/blob/main/osint-frontend/lib/apiClient.ts) | every backend call in one file |
| 9 | render | [`osint-frontend/components/`](https://github.com/BasilSuhail/OSINT/tree/main/osint-frontend/components) | map, cards, panels |

## 26.3 Where each source lands

| Source | Fetcher | Output |
| --- | --- | --- |
| GDELT live | [`app/sources/gdelt_fetcher.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/sources/gdelt_fetcher.py) | `events`, rolling window |
| GDELT history | [`app/composite/gdelt.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/composite/gdelt.py) | monthly checkpoints + daily volume |
| USGS · GDACS · FIRMS · EONET | [`app/sources/`](https://github.com/BasilSuhail/OSINT/tree/main/app/sources) | `events` → footprint enrichment |
| yfinance · FRED | [`app/sources/`](https://github.com/BasilSuhail/OSINT/tree/main/app/sources) | `events`, market and macro |
| ACLED (labels) | local drop folder ([§5.3](HANDBOOK.md#53-add-optional-source-access)) | `labels` — ground truth, kept separate |
| RSS, 55 feeds | [`app/sources/rss_feeds.json`](https://github.com/BasilSuhail/OSINT/blob/main/app/sources/rss_feeds.json) | `events` → stories |

## 26.4 Analytical subsystems — one folder each, formula inside

| Concern | Folder | Formula | Method in |
| --- | --- | --- | --- |
| Composite index | [`app/composite/`](https://github.com/BasilSuhail/OSINT/tree/main/app/composite) | `normalization.py` · `scoring.py` | [§14.4](HANDBOOK.md#144-the-composite-stress-index--and-why-the-live-one-reads-05) |
| Corroboration | [`app/corroboration/`](https://github.com/BasilSuhail/OSINT/tree/main/app/corroboration) | `score.py` | [§14.2](HANDBOOK.md#142-corroboration--how-much-independent-telling-a-story-has) |
| Telling divergence | [`app/disagreement/`](https://github.com/BasilSuhail/OSINT/tree/main/app/disagreement) | `tellings.py` | [§14.3](HANDBOOK.md#143-divergence--how-differently-two-country-blocs-word-the-same-story) |
| Lead-time gate | [`app/divergence/`](https://github.com/BasilSuhail/OSINT/tree/main/app/divergence) | `config.py` | [§14.8](HANDBOOK.md#148-the-lead-time-gate--does-narrative-move-before-the-physical-signal) |
| Country Instability Index | [`app/cii/`](https://github.com/BasilSuhail/OSINT/tree/main/app/cii) | `scoring.py` | [§14.9](HANDBOOK.md#149-the-country-instability-index-cii) |
| Prediction journal | [`app/journal/`](https://github.com/BasilSuhail/OSINT/tree/main/app/journal) | `emit.py` | [§15.10](HANDBOOK.md#1510-the-prediction-journal-the-hindcast-guard-and-the-degeneracy-check) |
| Evaluations | [`app/onset/`](https://github.com/BasilSuhail/OSINT/tree/main/app/onset) · [`app/within/`](https://github.com/BasilSuhail/OSINT/tree/main/app/within) · [`app/baselines/`](https://github.com/BasilSuhail/OSINT/tree/main/app/baselines) | — | [§15](HANDBOOK.md#15-evaluation--what-was-claimed-what-was-tested-what-failed) |
| Retention | [`app/housekeeping.py`](https://github.com/BasilSuhail/OSINT/blob/main/app/housekeeping.py) | — | [§11.3](HANDBOOK.md#113-retention-rule) |

---

# 27. Documentation index

This handbook is the entry point. The files below are the primary records it
draws on — read the protocol before the result, which is the order they were
written in.

| Document | What it is |
| --- | --- |
| [`docs/methodology.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/methodology.md) | Part A: the pre-registered evaluation protocol — ground truth, splits, baselines, metrics, sensitivity programme, reporting checklist. Part B: the literature baseline with citations and reading priority. |
| [`docs/onset-eval.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/onset-eval.md) | The onset evaluation, frozen 2026-07-10, with its single run and amendment log ([§15.6](HANDBOOK.md#156-result-2--the-onset-evaluation-2026-07-10)). |
| [`docs/within-country-eval.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/within-country-eval.md) | The within-country evaluation, frozen 2026-07-22, and its NEGATIVE verdict ([§15.7](HANDBOOK.md#157-result-3--the-within-country-evaluation-2026-07-22)). |
| [`docs/disagreement-exam.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/disagreement-exam.md) | A forward evaluation — not gradable until enough predictions mature. |
| [`docs/backtest/`](https://github.com/BasilSuhail/OSINT/tree/main/docs/backtest) | Lead-time gate reports, including threshold sensitivity ([§15.8](HANDBOOK.md#158-lead-time-and-its-sensitivity-to-the-threshold)). |
| [`docs/severity-grading.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/severity-grading.md) | How headline severity is decided, which model, and the measured agreement ([§14.5](HANDBOOK.md#145-severity--and-why-08-does-not-compare-across-families)). |
| [`docs/analytical-agenda.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/analytical-agenda.md) | The workstreams: what is actually done with the data — quantify, validate, predict. |
| [`docs/project-direction.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/project-direction.md) | What the project is, who it serves, and the long-term path. |
| [`docs/data-coverage.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/data-coverage.md) | The operational record of what actually landed in storage ([§16.3](HANDBOOK.md#163-event-data-concentration-measured)). |
| [`docs/storage.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/storage.md) | Storage layout, retention, move, back up, restore, wipe ([§11](HANDBOOK.md#11-data-storage-and-retention)). |
| [`docs/acled-non-api-collection.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/acled-non-api-collection.md) | How the label data is obtained without an API. |
| [`docs/security.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/security.md) | Repository security baseline: what is enabled, what hardening remains ([§25.4](#254-reporting-a-security-problem)). |
| [`docs/architecture/`](https://github.com/BasilSuhail/OSINT/tree/main/docs/architecture) | The build specification: [01 overview](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/01-overview.md) · [02 storage](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/02-storage.md) · [03 ingestion](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/03-ingestion.md) · [04 schema](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/04-schema.md) · [05 originality](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/05-originality.md) · [06 validation](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/06-validation.md) · [07 risks](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/07-risks.md) |
| [`docs/architecture/CII-METHODOLOGY.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/CII-METHODOLOGY.md) | Per-country baseline and the four-component event blend ([§14.9](HANDBOOK.md#149-the-country-instability-index-cii)). |
| [`docs/architecture/ENRICHMENT-METHODOLOGY.md`](https://github.com/BasilSuhail/OSINT/blob/main/docs/architecture/ENRICHMENT-METHODOLOGY.md) | Sentiment, NER, city resolution, news-scope classification. |
| [`docs/audits/`](https://github.com/BasilSuhail/OSINT/tree/main/docs/audits) · [`docs/frontend/`](https://github.com/BasilSuhail/OSINT/tree/main/docs/frontend) | Hand-checked audits; console design notes. |

---

# 28. SWOT

A candid read of where the project stands, kept with the code so it stays
current rather than becoming a pitch.

|  | Helpful | Harmful |
| --- | --- | --- |
| **Internal** | Strengths | Weaknesses |
| **External** | Opportunities | Threats |

## 28.1 Strengths

- A pre-registration and verdict machine that **structurally cannot flatter
  itself**: protocols frozen first, verdicts computed in code, negatives
  published in full, none buried ([§0.3](#03-what-is-actually-being-offered)).
- Reproducible, local-first, no cloud. Idempotent backfills, every method
  version-stamped and never edited in place.
- Genuine multi-modal ingestion with structural deduplication and **published**
  coverage bias rather than a disclaimer ([§16](HANDBOOK.md#16-bias-provenance-and-one-country-traced-end-to-end)).
- The corroboration and divergence engine works today and is independent of the
  composite claim that failed.

## 28.2 Weaknesses

- **The headline claim failed.** The composite beats none of the single-domain
  baselines, on either window ([§15.5](HANDBOOK.md#155-result-1--the-incidence-evaluation-2026-07-09)).
- **The running version has never been evaluated.** Every published result
  grades `v1.0`; the live system emits `v3.0` ([§14.1](HANDBOOK.md#141-what-fixed-before-running-means-in-this-repository)).
- **No forward evidence yet** — 1,695 predictions issued, none graded
  ([§15.10](HANDBOOK.md#1510-the-prediction-journal-the-hindcast-guard-and-the-degeneracy-check)).
- The live composite is degenerate at 0.5 from the retention-versus-z-score
  mismatch, and the label panel is maintained by hand.
- Five of six declared robustness tests have not been run
  ([§15.9](HANDBOOK.md#159-sensitivity-and-robustness--declared-and-honestly-incomplete)).
- Built by one maintainer with heavy assistance from language models; depth of
  understanding of the internals is the standing risk, and this handbook plus
  [§14](HANDBOOK.md#14-methods--every-number-the-system-publishes) is the mitigation.

## 28.3 Opportunities

- **Slow-onset hazards** — drought, flood, sustained unrest — are the untested
  anchor where a sensor could plausibly lead coverage. An open question, not a
  settled failure.
- The hazard domain is the strongest single indicator measured so far and beats
  the composite that contains it. Making it survive a fair onset evaluation is a
  well-defined next task.
- The corroboration and coverage engine has standalone value: it answers "is
  this independently reported" without needing the composite to work.

## 28.4 Threats

- **Upstream drift**: GDELT gaps, label-source access changes, RSS format
  changes, and sensor values that turn out to measure something other than what
  they appear to.
- **Retention versus evaluation needs** can silently flatten a signal before it
  is ever measured — the class of defect that produced 1,101 forecasts of a
  constant.
- The hardest questions to answer are the within-country construction and the
  0.5 degeneracy — both of which the composite's published results depend on.

---

---

**Start here:** [§0](#0-what-this-system-is-for-and-what-it-is-not) for what this
claims and refuses to claim, [Quick start](#quick-start) to run it, and
[HANDBOOK.md](HANDBOOK.md) for everything else.
