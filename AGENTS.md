# Working agreements

Read by coding agents (Claude Code, Codex, and anything else pointed at this
repository) and by people. `CLAUDE.md` is a symlink to this file so there is
one set of rules, not two that drift.

## This repository is public

It is public, it has been forked, and forks copy the full history. Anything
committed is beyond recall the moment it is pushed — deleting it later does
not reach the copies. Write every line as though a stranger will read it,
because one can.

## Never commit

**People.** No personal names, in code, comments, commit messages, issue or
pull-request text. This includes third parties — colleagues, reviewers,
anyone who did not choose to appear in a public repository. Their name is
their data, not ours.

Write the role the sentence actually means:

```
- Alice fills the accuracy columns        + the reviewer fills the accuracy columns
- lets Bob watch UK headlines             + lets the operator watch UK headlines
- Carol merges every PR herself           + the maintainer merges every PR
```

Rephrase rather than delete. Several comments explain *why* a design exists —
human-in-the-loop audit columns only make sense once you know a person fills
them — and deleting the sentence loses the reason with the name.

**Institutions and assessment.** No school, university, employer, course code,
degree, mark, deadline, or examination vocabulary. Describe the work, not
what it is being assessed for.

Degree words become work words; assessment words become reader words. Say
"project" and "report" for the thing, "a reader will ask" for the question,
"load-bearing for the claim" for what rests on it.

**Contact and location.** No personal email, phone number, address, or
home city. Commits use a `noreply.github.com` address; the pre-commit hook
enforces it.

**Credentials.** No keys, tokens, passwords, connection strings, private IPs.
Configuration belongs in `.env`, which is git-ignored.

**Career and personal aspiration.** What this project is for, professionally
or in study terms, is not documentation. It invites exactly the curiosity about
the author that the rest of this section exists to prevent.

## The rule that is easy to get wrong

**Do not enumerate the terms you are removing.** An earlier cleanup wrote the
names, the institution and the course code into a public issue in order to
describe removing them, and published more than it deleted. State the
category. Never the instance.

The pre-commit hook holds the actual patterns. It lives in `.git/hooks/`,
which is never pushed, and that is deliberate — it is the only place the
specifics can safely be written down.

## Enforcement

`.git/hooks/pre-commit` screens staged files and blocks the commit on a hit.
It is installed from `~/.git-templates/hooks/`, so new clones need:

```
git config --global init.templateDir ~/.git-templates
git init                                 # re-runs the template on an existing repo
```

A block is a prompt to rephrase, not an obstacle to route around.
`--no-verify` exists for the case the screen is genuinely wrong; reach for it
knowing that what you push cannot be unpushed.

## Workflow

One issue, one branch, one pull request, one commit. Always branch, always
open a PR. The maintainer merges — an agent never does.

Commit messages carry no attribution trailers: no `Co-Authored-By`, no
"generated with" line.

## Before you push

- Would a stranger reading this learn anything about a person? Remove it.
- Does a comment name someone where it means a role? Rephrase it.
- Is a number or claim in the text something you measured, or something you
  assumed? Say which.
