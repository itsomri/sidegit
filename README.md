# sidegit

**Store arbitrary structured data and files alongside your git commits.**

sidegit is a small HTTP server + CLI that lets you attach JSON payloads and file blobs to git commits, query them back, and read your repo's refs and log over HTTP. It was built with performance benchmark results and artifacts (like profiler outputs) in mind, and this concept will be used extensively in the docs and examples, but the API and data model are unopinionated about *what* you store and may prove useful for a wider variety of use cases.

```text
        git history                  sidegit
   ─────────────────────────    ─────────────────────────
   commit deadbeef  ──────►     records keyed by deadbeef
     ├─ tree                      ├─ {"latency_ms": 12.3}
     ├─ parent                    ├─ tags {"env": "ci"}
     └─ message                   └─ blobs: profile.pprof, log.txt
```

> **v0.1 has no authentication.** Run it on a trusted network, behind your VPN, or under an authenticating reverse proxy. Auth lands in a later release.

## Install

```bash
pip install sidegit
```

Or run the Docker image:

```bash
docker run -p 5000:8080 -v "$PWD:/repo" -e SIDEGIT_REPO_DIR=/repo ghcr.io/itsomri/sidegit:latest
```

## 60-second quickstart

```bash
# 1. Start the server (uses ./data for storage, current dir as the git repo)
sidegit serve

# 2. In another shell — attach data to the current commit
COMMIT=$(git rev-parse HEAD)
sidegit create-record "$COMMIT" \
    --data '{"latency_ms": 12.3, "throughput_rps": 4200}' \
    --tag env=ci --tag suite=nightly
# → prints {"id": "...", "commit_hash": "...", ...}

# 3. Attach a file (profiler output, log, anything)
RECORD=$(sidegit list-records --commit-hash "$COMMIT" | jq -r '.[0].id')
sidegit upload-blob "$RECORD" ./profile.pprof

# 4. Read it back
sidegit get-record "$RECORD"
curl http://127.0.0.1:5000/api/records?commit_hash=$COMMIT
```

## Data model

**`records`** — a thing attached to a commit. There is no limit to the amount of records per commit. In the context of performance testing, a "record" can be thought of as a single execution of a benchmark. Several records of a benchmark can be created in various environments (a local dev machine, a remote server, a CI action, etc), and can be queried independently. Records can be tagged and filtered - for example, a user might want to get all records of a specific benchmark on a specific setup and compare them. 

| field | type | notes |
|---|---|---|
| `id` | string (UUID) | primary key |
| `commit_hash` | string | required; canonical git SHA — 40 hex chars (SHA-1) or 64 (SHA-256). Refs and tags are not accepted by the API. See ["Why canonical SHAs only?"](#why-canonical-shas-only). |
| `timestamp` | datetime | server-assigned |
| `data` | JSON | your arbitrary payload |
| `tags` | JSON object (key→string) | for filtering — e.g. `{"env": "ci", "suite": "nightly"}` |

**`blobs`** — files attached to a record. In the context of performance benchmarks, this could be the profiler output.

| field | type | notes |
|---|---|---|
| `id` | string (UUID) | primary key |
| `record_id` | FK | required; cascade-deletes with the record |
| `name` | string | display name |
| `mime_type` | string | guessed if not provided |
| `size_bytes` | int | |
| `extra` | JSON | arbitrary metadata |

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/records` | Create. Body: `{commit_hash, data?, tags?, id?}` |
| `GET` | `/api/records` | List. Query: `?commit_hash=`, `?tag=k:v` |
| `GET` | `/api/records/<id>` | Read one (includes blob metadata) |
| `DELETE` | `/api/records/<id>` | Delete (cascades blobs) |
| `POST` | `/api/records/<id>/blobs` | Upload blob (multipart, field `file`) |
| `GET` | `/api/blobs/<id>` | Download blob (302 to presigned URL in S3 mode) |
| `DELETE` | `/api/blobs/<id>` | Delete one blob |
| `GET` | `/api/git/refs` | List branches, tags, HEAD |
| `GET` | `/api/git/log?ref=&limit=` | Commit log for a ref |

The `/api/git/*` endpoints return 404 when sidegit isn't pointed at a git repo.

## Why canonical SHAs only?

Records are intentionally strictly coupled to a commit. Using a `commit_hash` (and not general git refs) removes ambiguity - for example, a client might have an outdated local branch. Anything other than a full git SHA is potentially ambiguous.

The CLI smooths this over: when you run `sidegit create-record HEAD` (or any ref, tag, or short SHA), the CLI shells out to `git rev-parse` in your local repo, resolves it to the canonical 40-char SHA, and posts that. Resolution happens once, at write time, against the repo *you* have — so the stored value is permanent.

If you want to stash a release tag or an image digest on the record, put it in `tags`.

## Configuration

sidegit is configured by a YAML file. Env vars and CLI flags override individual values from the file — useful for injecting secrets at runtime or for one-off overrides without editing the config.

**Precedence, later wins:** built-in defaults → config file → env vars → CLI flags.

**Where the file is read from** (first match wins):

1. `--config <path>` flag
2. `SIDEGIT_CONFIG` env var
3. `./sidegit.yaml` (project-local)
4. `/etc/sidegit/config.yaml` (system-wide)
5. Built-in defaults if nothing else is found

A full annotated example lives in [`sidegit.example.yaml`](./sidegit.example.yaml). The defaults shown below are what you get with no config file at all:

```yaml
data_dir: ./data
repo_dir: .

server:
  host: 127.0.0.1
  port: 5000

database:
  url: null            # null → SQLite under {data_dir}/sidegit.db

storage:
  s3_bucket: null      # null → local FS under {data_dir}/blobs
  s3_endpoint_url: null
```

### Env-var overrides

Use env vars for secrets and per-deployment values you don't want pinned in a file.

| Env var | Overrides | Notes |
|---|---|---|
| `SIDEGIT_CONFIG` | (the config-file path itself) | Alternative to `--config`. |
| `SIDEGIT_DATA_DIR` | `data_dir` | |
| `SIDEGIT_REPO_DIR` | `repo_dir` | |
| `SIDEGIT_HOST` | `server.host` | |
| `SIDEGIT_PORT` | `server.port` | Coerced to int. |
| `DATABASE_URL` | `database.url` | Universal convention — Heroku, Fly, Render, Railway all use this name. |
| `SIDEGIT_S3_BUCKET` | `storage.s3_bucket` | |
| `SIDEGIT_S3_ENDPOINT_URL` | `storage.s3_endpoint_url` | |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | (passed through to boto3) | sidegit doesn't read these; boto3 picks them up automatically. |

## Examples

See [`examples/`](./examples/) for a GitHub Actions workflow that records a benchmark on every commit and a `pytest-benchmark` adapter.

## Why not just `git notes`?

`git notes` is great for plain text attached to commits, but it doesn't scale to file uploads, has no query API, and isn't accessible from CI environments that don't have your repo cloned. sidegit gives you an HTTP boundary over the same idea.

## Development

```bash
git clone https://github.com/itsomri/sidegit
cd sidegit
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pytest
```

## License

Apache-2.0 — see [LICENSE](./LICENSE).
