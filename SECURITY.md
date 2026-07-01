# Security

## Reporting vulnerabilities

If you find a security issue, please report it privately via:

- GitHub private vulnerability reporting on this repository
- Or direct message to the repository maintainer: `BasilSuhail@users.noreply.github.com`

Please include:

- Affected endpoint/version
- Reproduction steps
- Impact assessment
- Suggested fix (if available)

## Security automation in this repository

- **Dependabot**: checks `pip` and `pnpm` dependencies weekly and opens PRs for updates.
- **CodeQL**: runs on push, pull requests, and weekly scan schedule to surface code vulnerabilities.
- **Security checks in CI**:
  - Backend: `pip-audit` against `requirements.txt` in `backend` workflow.
  - Frontend: `pnpm audit --audit-level high` in `frontend` workflow.
  - PR dependency review (`actions/dependency-review-action`) blocks high-severity dependency regressions.
- **GitHub secret scanning**: enabled at repository level.
  - Push protection: enabled.
  - Non-provider pattern scans and validity checks were attempted via API but remain manual in this repo UI context.

## GitHub repo baseline for security

Expected defaults for this project:

- Security alerts enabled (`Code scanning`, `Dependabot alerts`, `Dependabot updates`)
- Protected `main` branch with pull-request checks and review workflow
- No secrets in source control (`.env` values are local only)
- CI status required before merge
