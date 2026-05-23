# Contributing to sidegit

sidegit aims to stay **small and unopinionated** — its job is to be the boring, reliable plumbing under more interesting tools. 

## What belongs in sidegit

- The `records` + `blobs` data model and CRUD over it
- Git-read endpoints (`refs`, `log`)
- Storage backends (local FS, S3-compatible)
- Things that are necessary for *any* consumer

## What does not belong in sidegit

If you can build it on top of the API, it doesn't go in core:

- Metric series tables, aggregations, alerts
- Comparison or diff endpoints
- Plotting, charts, dashboards
- Domain-specific schemas (perf, ML, CI artifacts…)
- A UI

## Development setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## Pull requests

- One logical change per PR.
- Add or update tests for any behavior change. New endpoints get integration tests in `tests/`.
- Keep the public API stable when possible. Breaking changes need a CHANGELOG entry and a version bump.
- Run `pytest` and `ruff check .` before opening the PR.

## Reporting bugs

Open an issue with: the version (`pip show sidegit`), what you ran, what happened, what you expected. A minimal reproduction is worth a lot.

## Reporting security issues

See [SECURITY.md](./SECURITY.md).
