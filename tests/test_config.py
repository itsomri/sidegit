"""Tests for the layered config loader."""
import textwrap

import pytest

from sidegit.config import DEFAULTS, load_config, to_flask_config


class TestDefaults:
    def test_no_file_no_env_returns_defaults(self, tmp_path, monkeypatch):
        # Run in an empty cwd, no env, no overrides.
        monkeypatch.chdir(tmp_path)
        cfg = load_config(env={})
        assert cfg["data_dir"] == DEFAULTS["data_dir"]
        assert cfg["server"]["host"] == "127.0.0.1"
        assert cfg["server"]["port"] == 5000
        assert cfg["database"]["url"] is None
        assert cfg["storage"]["s3_bucket"] is None


class TestFileLoading:
    def _write(self, path, text):
        path.write_text(textwrap.dedent(text))

    def test_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "my.yaml"
        self._write(cfg_file, """
            data_dir: /var/data
            server:
              port: 9000
        """)
        cfg = load_config(config_path=str(cfg_file), env={})
        assert cfg["data_dir"] == "/var/data"
        assert cfg["server"]["port"] == 9000
        # Untouched key keeps its default
        assert cfg["server"]["host"] == "127.0.0.1"

    def test_search_path_picks_cwd_first(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._write(tmp_path / "sidegit.yaml", "data_dir: /from/cwd\n")
        cfg = load_config(env={})
        assert cfg["data_dir"] == "/from/cwd"
        assert cfg["_config_path"].endswith("sidegit.yaml")

    def test_search_path_skipped_when_no_file_exists(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config(env={})
        assert "_config_path" not in cfg

    def test_env_var_picks_config_path(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "via-env.yaml"
        self._write(cfg_file, "data_dir: /via/env\n")
        monkeypatch.chdir(tmp_path)
        cfg = load_config(env={"SIDEGIT_CONFIG": str(cfg_file)})
        assert cfg["data_dir"] == "/via/env"

    def test_rejects_non_mapping_yaml(self, tmp_path):
        cfg_file = tmp_path / "bad.yaml"
        cfg_file.write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="mapping"):
            load_config(config_path=str(cfg_file), env={})


class TestEnvOverrides:
    def test_env_overrides_file(self, tmp_path):
        cfg_file = tmp_path / "c.yaml"
        cfg_file.write_text("server:\n  port: 7000\n")
        cfg = load_config(
            config_path=str(cfg_file),
            env={"SIDEGIT_PORT": "8888"},
        )
        assert cfg["server"]["port"] == 8888  # coerced to int

    def test_database_url_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config(env={"DATABASE_URL": "postgresql://x/y"})
        assert cfg["database"]["url"] == "postgresql://x/y"

    def test_empty_string_env_does_not_override(self, tmp_path):
        cfg_file = tmp_path / "c.yaml"
        cfg_file.write_text("data_dir: /from/file\n")
        cfg = load_config(config_path=str(cfg_file), env={"SIDEGIT_DATA_DIR": ""})
        # Empty string = "not set" — file value wins
        assert cfg["data_dir"] == "/from/file"


class TestCliOverrides:
    def test_cli_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config(
            env={"SIDEGIT_PORT": "8888"},
            overrides={"server": {"port": 9999}},
        )
        assert cfg["server"]["port"] == 9999

    def test_cli_none_values_do_not_clobber(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config(
            env={"SIDEGIT_PORT": "8888"},
            overrides={"server": {"port": None, "host": "0.0.0.0"}},
        )
        # port=None should be dropped, env value preserved
        assert cfg["server"]["port"] == 8888
        assert cfg["server"]["host"] == "0.0.0.0"


class TestToFlaskConfig:
    def test_sqlite_default(self, tmp_path):
        cfg = load_config(config_path=None, env={"SIDEGIT_DATA_DIR": str(tmp_path)})
        flask = to_flask_config(cfg)
        assert flask["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")
        assert flask["SQLALCHEMY_DATABASE_URI"].endswith("sidegit.db")
        assert flask["BLOB_STORAGE_DIR"].endswith("blobs")

    def test_postgres_passthrough(self, tmp_path):
        cfg = load_config(env={"DATABASE_URL": "postgresql://u@h/db", "SIDEGIT_DATA_DIR": str(tmp_path)})
        flask = to_flask_config(cfg)
        assert flask["SQLALCHEMY_DATABASE_URI"] == "postgresql://u@h/db"

    def test_heroku_url_normalized(self, tmp_path):
        cfg = load_config(env={"DATABASE_URL": "postgres://u@h/db", "SIDEGIT_DATA_DIR": str(tmp_path)})
        flask = to_flask_config(cfg)
        assert flask["SQLALCHEMY_DATABASE_URI"].startswith("postgresql://")
