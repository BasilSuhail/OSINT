# GitHub Security Baseline

## What is now enabled

- Dependabot for:
  - `pip` updates under repository root (`app`, backend service)
  - `pnpm` updates under `osint-frontend`
- Code scanning via CodeQL:
  - Python
  - JavaScript/TypeScript
- CI security checks:
  - Backend dependency audit using `pip-audit`
  - Frontend dependency audit using `pnpm audit --audit-level high`
- GitGuardian security checks (existing in repo settings)

## Recommended follow-up hardening

- Enforce branch protection rules with:
  - PR review requirements
  - Required status checks (`backend`, `frontend`, `codeql`, `test`)
  - `main` linear-history disabled only if explicitly needed for merge strategy
- Enable Dependabot security updates for all ecosystems once update noise is validated
- Add secret rotation/incident process docs to incident response runbook
- Add a vulnerability triage rotation for newly opened alerts
- Expand CI to include container image scans when Docker images are published
