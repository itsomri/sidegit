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