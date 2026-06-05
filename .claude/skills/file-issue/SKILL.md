---
name: file-issue
description: File a self-contained GitHub issue for a bug report or feature request in the Pringle conventions (planner role). Use when the user reports a bug, requests a feature, or asks to log/track/write up work as an issue.
---

# File a Pringle Issue (Planner)

This is the planner role's core procedure. Full role definition: [design-docs/roles/planner.md](../../../design-docs/roles/planner.md).

**Hard constraint:** the planner does NOT modify code files. Analyze code and suggest changes *inside the issue body* only.

## Before filing — evaluate tradeoffs

Assess the request for meaningful **performance impact** or **code-complexity increase**. If either is a concern, present it to the user and get explicit acceptance of the tradeoff *before* logging the issue. Do not silently file something with hidden cost.

## Write a self-contained issue

The body must stand alone — a developer should be able to implement from it without re-interviewing the user. Include:

- **Context / problem** — what's wrong or what's wanted, and why.
- **Repro steps** (bugs) or **desired behavior** (features).
- **Affected code** — concrete `file:line` pointers from reading the codebase, with suggested changes where you can support them.
- **Acceptance criteria** — how "done" is verified (tests, benchmark PASS, visual frame, etc.).

## Create it

```bash
gh issue create --title "<TYPE>: <concise summary>" --body "<self-contained body>" --label "<label>"
```

**Title prefixes** (match existing repo style): `BUG:`, `FEAT:`, `PERF-NNN:`, `ARCH:`.

**Labels** (combine a type with a severity where it helps):
- type: `bug`, `feature`, `performance`, `documentation`
- severity: `critical` (crash/data loss), `high`, `medium`, `low`
- `benchmark` — issue carries benchmark numbers

Check existing issues first to avoid duplicates and to get the next `PERF-NNN` number: `gh issue list` / `gh issue list --state closed`.

## Closing

When a fix merges: `gh issue close <N> --comment "Fixed in <commit/PR>"`. For perf issues, post before/after numbers.
