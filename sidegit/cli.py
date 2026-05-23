"""sidegit CLI — thin wrapper over the HTTP API plus an embedded server runner."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys

import requests

from sidegit.config import load_config

_SHA_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


def _resolve_commit_hash(value: str, repo_dir: str | None = None) -> str:
    """Resolve `value` to a canonical commit SHA via `git rev-parse`.

    If `value` already looks like a canonical SHA, return it unchanged
    (no git call needed). Otherwise shell out to git in `repo_dir` (or cwd).
    Raises SystemExit with a clear message if resolution fails.
    """
    if _SHA_RE.match(value):
        return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{value}^{{commit}}"],
            cwd=repo_dir, capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        raise SystemExit("git is not installed or not on PATH; cannot resolve ref") from None
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or "").strip() or f"could not resolve '{value}'"
        raise SystemExit(
            f"Failed to resolve '{value}' to a commit: {msg}\n"
            "Pass a full git SHA, or run this from inside a git repo where the ref exists."
        ) from None
    return result.stdout.strip()


def _resolve_server(args) -> tuple[str, int]:
    """Pick host/port using layered config: file → env → CLI flags."""
    cli_overrides: dict = {"server": {}}
    if getattr(args, "host", None):
        cli_overrides["server"]["host"] = args.host
    if getattr(args, "port", None):
        cli_overrides["server"]["port"] = args.port
    cfg = load_config(
        config_path=getattr(args, "config", None),
        overrides=cli_overrides if cli_overrides["server"] else None,
    )
    return cfg["server"]["host"], int(cfg["server"]["port"])


def _base_url(args) -> str:
    host, port = _resolve_server(args)
    return f"http://{host}:{port}/api"


def _print_response(res):
    try:
        print(json.dumps(res.json(), indent=2))
    except ValueError:
        print(res.text)


def _load_json_arg(inline: str | None, path: str | None, label: str) -> dict | None:
    """Read a JSON object from `--data '{...}'` or `--data-file path` (or stdin via `-`)."""
    out: dict = {}
    if path:
        text = sys.stdin.read() if path == "-" else open(path).read()
        if text.strip():
            out.update(json.loads(text))
    if inline:
        out.update(json.loads(inline))
    return out or None if (inline or path) else None


def _parse_tags(pairs: list[str]) -> dict[str, str]:
    tags = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"--tag must be key=value, got: {p}")
        k, _, v = p.partition("=")
        tags[k] = v
    return tags


def cmd_create_record(args):
    commit_hash = _resolve_commit_hash(args.commit_hash, repo_dir=args.repo_dir)
    payload = {"commit_hash": commit_hash}
    data = _load_json_arg(args.data, args.data_file, "data")
    if data is not None:
        payload["data"] = data
    tags = _parse_tags(args.tag)
    if tags:
        payload["tags"] = tags
    res = requests.post(f"{_base_url(args)}/records", json=payload, timeout=30)
    res.raise_for_status()
    _print_response(res)


def cmd_list_records(args):
    params = {}
    if args.commit_hash:
        params["commit_hash"] = args.commit_hash
    if args.tag:
        if "=" not in args.tag:
            raise SystemExit("--tag must be key=value")
        k, _, v = args.tag.partition("=")
        params["tag"] = f"{k}:{v}"
    res = requests.get(f"{_base_url(args)}/records", params=params, timeout=30)
    res.raise_for_status()
    _print_response(res)


def cmd_get_record(args):
    res = requests.get(f"{_base_url(args)}/records/{args.record_id}", timeout=30)
    res.raise_for_status()
    _print_response(res)


def cmd_delete_record(args):
    res = requests.delete(f"{_base_url(args)}/records/{args.record_id}", timeout=30)
    res.raise_for_status()
    _print_response(res)


def cmd_upload_blob(args):
    if not os.path.exists(args.file_path):
        raise SystemExit(f"File not found: {args.file_path}")
    mime_type = args.mime_type or mimetypes.guess_type(args.file_path)[0] or "application/octet-stream"
    data = {"name": args.name or os.path.basename(args.file_path), "mime_type": mime_type}
    if args.extra:
        data["extra"] = args.extra
    with open(args.file_path, "rb") as f:
        files = {"file": (os.path.basename(args.file_path), f, mime_type)}
        res = requests.post(
            f"{_base_url(args)}/records/{args.record_id}/blobs",
            files=files, data=data, timeout=300,
        )
    res.raise_for_status()
    _print_response(res)


def cmd_delete_blob(args):
    res = requests.delete(f"{_base_url(args)}/blobs/{args.blob_id}", timeout=30)
    res.raise_for_status()
    _print_response(res)


def cmd_serve(args):
    """Build CLI overrides, hand the merged config to create_app(), and run."""
    from sidegit.app import create_app
    from sidegit.config import to_flask_config

    overrides: dict = {"server": {}, "database": {}, "storage": {}}
    if args.host:
        overrides["server"]["host"] = args.host
    if args.port:
        overrides["server"]["port"] = args.port
    if args.data_dir:
        overrides["data_dir"] = args.data_dir
    if args.repo_dir:
        overrides["repo_dir"] = args.repo_dir

    cfg = load_config(config_path=args.config, overrides=overrides)
    flask_cfg = to_flask_config(cfg)

    # Same git-loading logic as create_app's production path, but we already
    # know the resolved config — pass it straight through.
    import git  # noqa: PLC0415
    os.makedirs(flask_cfg["SIDEGIT_DATA_DIR"], exist_ok=True)
    os.makedirs(flask_cfg["BLOB_STORAGE_DIR"], exist_ok=True)
    try:
        repo = git.Repo(flask_cfg["SIDEGIT_REPO_DIR"], search_parent_directories=True)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        repo = None
    flask_cfg["GIT_REPO"] = repo

    app = create_app(flask_cfg)
    host, port = flask_cfg["SIDEGIT_HOST"], flask_cfg["SIDEGIT_PORT"]
    print(f"sidegit listening on http://{host}:{port}"
          + (f" (config: {cfg['_config_path']})" if cfg.get("_config_path") else ""))
    app.run(host=host, port=port, debug=False)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sidegit", description="Store data and files alongside git commits.")
    p.add_argument("--config", help="Path to a sidegit.yaml config file. "
                                    "Overrides SIDEGIT_CONFIG env var and the default search path.")
    p.add_argument("--host", help="Override server.host (where the CLI talks to or where serve listens).")
    p.add_argument("--port", type=int, help="Override server.port.")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="Run the sidegit server.")
    s.add_argument("--data-dir", help="Override data_dir from config.")
    s.add_argument("--repo-dir", help="Override repo_dir from config.")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("create-record",
                       help="Create a record attached to a commit (ref or SHA).")
    s.add_argument("commit_hash",
                   help="Git ref (e.g. HEAD, main, v1.0) or full SHA. "
                        "Refs are resolved locally via `git rev-parse` before posting.")
    s.add_argument("--data", help="Inline JSON object for the record's data field.")
    s.add_argument("--data-file", help="Path to a JSON file (or '-' for stdin) for the data field.")
    s.add_argument("--tag", action="append", default=[], metavar="K=V",
                   help="Tag key=value (repeatable).")
    s.add_argument("--repo-dir",
                   help="Local git repo to resolve refs against (default: current directory).")
    s.set_defaults(func=cmd_create_record)

    s = sub.add_parser("list-records", help="List records, optionally filtered.")
    s.add_argument("--commit-hash")
    s.add_argument("--tag", metavar="K=V")
    s.set_defaults(func=cmd_list_records)

    s = sub.add_parser("get-record", help="Fetch one record (with blob metadata).")
    s.add_argument("record_id")
    s.set_defaults(func=cmd_get_record)

    s = sub.add_parser("delete-record", help="Delete a record and its blobs.")
    s.add_argument("record_id")
    s.set_defaults(func=cmd_delete_record)

    s = sub.add_parser("upload-blob", help="Attach a file to a record.")
    s.add_argument("record_id")
    s.add_argument("file_path")
    s.add_argument("--name", help="Override the blob name (defaults to filename).")
    s.add_argument("--mime-type", dest="mime_type", help="MIME type (guessed if omitted).")
    s.add_argument("--extra", help="Inline JSON object for the blob's extra field.")
    s.set_defaults(func=cmd_upload_blob)

    s = sub.add_parser("delete-blob", help="Delete a single blob.")
    s.add_argument("blob_id")
    s.set_defaults(func=cmd_delete_blob)

    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
