# GitHub + Dokploy workflow

This repo should use **two long-lived branches** with different jobs:

- `main` = integration branch for normal work, PRs, fixes, and feature merges
- `production` = deploy branch watched by Dokploy

Dokploy should deploy **only** `production`, never `main`.

---

## Desired flow

1. Create a feature branch from `main`
2. Open a PR into `main`
3. Let CI pass and review the change
4. Merge into `main`
5. When ready to deploy, open a PR from `main` into `production`
6. Merge that PR only when you want Dokploy to update the server

This gives you one server-safe revision collecting data while GitHub keeps
moving forward on `main`.

---

## Why this matters for OSINT

OSINT has two separate states:

- **code state**: what revision Dokploy is running
- **data state**: what is stored under `OSINT_DATA_DIR`

The code can change often. The data should survive for a long time.

Deploying from `production` means you can:

- leave a stable collector running for weeks or months
- keep pushing PRs and experiments to GitHub
- choose exactly when the server should move to a newer revision

---

## Required GitHub settings

Apply branch protection to both `main` and `production`.

### `main`

- require a pull request before merging
- require at least 1 approval
- dismiss stale approvals when new commits are pushed
- require status checks to pass before merging
- require branches to be up to date before merging
- block force pushes
- block branch deletion

Recommended required checks:

- `backend / test`
- `frontend / build`
- `dependency-review / review`
- `codeql / analyze (python)`
- `codeql / analyze (javascript)`

### `production`

- require a pull request before merging
- require at least 1 approval
- dismiss stale approvals when new commits are pushed
- require status checks to pass before merging
- require branches to be up to date before merging
- block force pushes
- block branch deletion
- restrict pushes so nobody pushes directly

Recommended required checks:

- `production-guardrails / production-source-check`
- any deploy-smoke or migration checks you later add

`production` PRs should come only from `main`.

---

## Repo guardrails committed here

- `.github/pull_request_template.md` forces deploy-impact thinking in every PR
- `.github/workflows/production-guardrails.yml` blocks PRs into `production`
  unless they come from `main`
- `.githooks/pre-push` blocks direct local pushes to `main` and `production`

Enable the local hook in each clone:

```bash
git config core.hooksPath .githooks
chmod +x .githooks/pre-push
```

---

## Dokploy settings

- connect Dokploy to the repo
- set branch to `production`
- disable auto-deploys from branches other than `production`
- set `OSINT_DATA_DIR` to a persistent host path
- mount that path so Postgres/Redis survive redeploys

Suggested persistent path:

```text
/srv/osint-data
```

Suggested contents:

```text
/srv/osint-data/
├── postgres/
├── redis/
├── exports/
└── private/
```

Dokploy should replace containers and code, not this directory.

---

## First-time setup checklist

1. Create `production` from the current stable `main`
2. Protect `main`
3. Protect `production`
4. Point Dokploy at `production`
5. Set `OSINT_DATA_DIR` to the persistent server path
6. Verify retention is running daily
7. Verify direct pushes to `main` and `production` are blocked
