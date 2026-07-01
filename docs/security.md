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
- Main branch protection (API-applied):
  - No reviewer minimums (solo dev workflow)
  - Required status checks: `test`, `build`, `analyze (python)`, `analyze (javascript)`
  - Required conversation resolution
  - No force pushes/deletions

## Recommended follow-up hardening

- Add secret rotation/incident process docs to incident response runbook
- Add a vulnerability triage rotation for newly opened alerts
- Expand CI to include container image scans when Docker images are published

## Optional next hardening step (ready for this repo)

- Enable:
  - non-provider secret patterns
  - secret validity checks
- Add CODEOWNERS and required approval from security owner for config/security-sensitive files.
