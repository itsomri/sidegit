# Security

## v0.1 threat model

**sidegit v0.1 has no authentication at the moment.** Any client that can reach the HTTP port can:

- Read, create, and delete records and blobs.
- Read your repo's branch list, tag list, and commit log via `/api/git/*`.

This is intentional for v0.1 — sidegit is meant to be deployed on a trusted network (a private VPC, a developer machine, behind a corporate VPN) or behind an authenticating reverse proxy you control. Auth is on the roadmap for a later release.

**Do not expose a sidegit instance to the public internet without putting an auth layer in front of it.** Reasonable options:

- An authenticating reverse proxy (Caddy with `forward_auth`, nginx with `auth_request`, an oauth2-proxy sidecar).
- A service mesh that enforces mTLS or JWT.
- A network-level restriction (security groups, firewall rules).

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Use GitHub's [Private Vulnerability Reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability) instead — from the repository's **Security** tab, click **Report a vulnerability**. That creates a private advisory only maintainers can see.

We'll acknowledge as soon as possible, work on a fix, and credit you in the release notes unless you'd prefer to stay anonymous.

## Scope

In scope:

- Path traversal or arbitrary file access via the blob storage layer.
- SQL injection or other unsanitized-input issues.
- Cross-origin or request-smuggling issues that survive a reasonable proxy setup.

Out of scope for v0.1:

- "An unauthenticated user can read records" — that's the documented threat model.
- DoS via large uploads or many requests — deploy behind a reverse proxy with rate limits.
