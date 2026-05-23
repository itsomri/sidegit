"""Layered config loader for sidegit.

Precedence (later wins): defaults → config file → env vars → CLI overrides.

Public surface:
    load_config(config_path=None, overrides=None) -> dict
    to_flask_config(cfg, base_dir=None) -> dict   # nested → flat Flask keys
"""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "data_dir": "./data",
    "repo_dir": ".",
    "server": {
        "host": "127.0.0.1",
        "port": 5000,
    },
    "database": {
        "url": None,   # None → SQLite under {data_dir}/sidegit.db
    },
    "storage": {
        "s3_bucket": None,         # None → local FS under {data_dir}/blobs
        "s3_endpoint_url": None,
    },
}

# Env var → dotted path into the config tree. Listed in increasing override order
# isn't meaningful — env vars all sit at the same layer.
_ENV_MAP: dict[str, tuple[str, ...]] = {
    "SIDEGIT_DATA_DIR": ("data_dir",),
    "SIDEGIT_REPO_DIR": ("repo_dir",),
    "SIDEGIT_HOST": ("server", "host"),
    "SIDEGIT_PORT": ("server", "port"),
    "DATABASE_URL": ("database", "url"),
    "SIDEGIT_S3_BUCKET": ("storage", "s3_bucket"),
    "SIDEGIT_S3_ENDPOINT_URL": ("storage", "s3_endpoint_url"),
}

# Keys that must be coerced from str to int when arriving from env or CLI.
_INT_PATHS: set[tuple[str, ...]] = {("server", "port")}

DEFAULT_SEARCH_PATHS = (
    "./sidegit.yaml",
    "/etc/sidegit/config.yaml",
)


def _deep_merge(base: dict, overlay: dict) -> None:
    """Recursively merge overlay into base. Dicts merge, scalars overwrite."""
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _set_path(cfg: dict, path: tuple[str, ...], value: Any) -> None:
    """Set a nested key, creating intermediate dicts as needed."""
    cur = cfg
    for part in path[:-1]:
        cur = cur.setdefault(part, {})
    if path in _INT_PATHS and isinstance(value, str):
        value = int(value)
    cur[path[-1]] = value


def _discover_config_path(explicit: str | None, env: dict[str, str]) -> str | None:
    """Resolve which config file to read, if any."""
    if explicit:
        return explicit
    env_path = env.get("SIDEGIT_CONFIG")
    if env_path:
        return env_path
    for candidate in DEFAULT_SEARCH_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def load_config(
    config_path: str | None = None,
    overrides: dict | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    """Load and merge config from all layers. `env` is for tests; defaults to os.environ."""
    env = env if env is not None else os.environ
    cfg = copy.deepcopy(DEFAULTS)

    path = _discover_config_path(config_path, env)
    if path:
        with open(path) as f:
            file_cfg = yaml.safe_load(f) or {}
        if not isinstance(file_cfg, dict):
            raise ValueError(f"Config file {path} must contain a YAML mapping at the top level")
        _deep_merge(cfg, file_cfg)
        cfg["_config_path"] = path

    for env_key, dotted in _ENV_MAP.items():
        val = env.get(env_key)
        if val is not None and val != "":
            _set_path(cfg, dotted, val)

    if overrides:
        # Drop None values from overrides so CLI flags that weren't passed don't
        # clobber file/env values with None.
        cleaned = _strip_nones(overrides)
        _deep_merge(cfg, cleaned)

    return cfg


def _strip_nones(d: dict) -> dict:
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, dict):
            sub = _strip_nones(v)
            if sub:
                out[k] = sub
        elif v is not None:
            out[k] = v
    return out


def to_flask_config(cfg: dict) -> dict:
    """Translate nested config into the flat keys create_app() / Flask expect."""
    data_dir = os.path.abspath(cfg["data_dir"])
    blob_dir = os.path.join(data_dir, "blobs")

    database_url = cfg["database"]["url"]
    if database_url and database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    if not database_url:
        database_url = "sqlite:///" + os.path.join(data_dir, "sidegit.db")

    return {
        "SIDEGIT_DATA_DIR": data_dir,
        "SIDEGIT_REPO_DIR": os.path.abspath(cfg["repo_dir"]),
        "BLOB_STORAGE_DIR": blob_dir,
        "SQLALCHEMY_DATABASE_URI": database_url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "S3_BUCKET": cfg["storage"]["s3_bucket"],
        "S3_ENDPOINT_URL": cfg["storage"]["s3_endpoint_url"],
        "SIDEGIT_HOST": cfg["server"]["host"],
        "SIDEGIT_PORT": int(cfg["server"]["port"]),
    }
