# Security Policy

This repository hosts course material and the guardrail "spine" for a coding-agent
cursus. It runs no production service and stores no secrets — but because the cohort
works in a shared repository, and because the course itself teaches secret-scanning and
supply-chain discipline, we treat security reports seriously and practice what we teach.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** rather than opening a public issue:

- Use GitHub's **Report a vulnerability** button under the repository's **Security** tab
  (available when private vulnerability reporting is enabled), or
- email the maintainer at **guilhem.busset@gmail.com**.

Include enough detail to reproduce: the affected file or workflow, the steps involved,
and the impact.

If you discover a **leaked credential** committed to the repository, report it privately
and do **not** open a public issue or PR that references it.

## Scope

In scope: the guardrail spine (`.githooks/`, `.github/workflows/`, `.claude/`,
`scripts/`) and any secret accidentally committed to the repository.

Out of scope: third-party tools and services the course merely references or links to.

## Response

This is a course repository maintained by a single instructor, so response times follow
the teaching calendar; we aim to acknowledge a report within a few business days.
