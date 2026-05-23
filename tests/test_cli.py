"""Tests for the CLI's local git ref resolution."""
import subprocess

import pytest

from sidegit.cli import _resolve_commit_hash


def _init_repo(path):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "f.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "one"], cwd=path, check=True)
    subprocess.run(["git", "tag", "v1"], cwd=path, check=True)


class TestResolveCommitHash:
    def test_full_sha1_passes_through(self):
        sha = "f" * 40
        assert _resolve_commit_hash(sha) == sha

    def test_full_sha256_passes_through(self):
        sha = "a" * 64
        assert _resolve_commit_hash(sha) == sha

    def test_uppercase_sha_not_treated_as_canonical(self, tmp_path):
        # Uppercase doesn't match the regex; treat as a ref. Resolution will fail
        # outside a repo, so we expect SystemExit (not pass-through).
        with pytest.raises(SystemExit):
            _resolve_commit_hash("A" * 40, repo_dir=str(tmp_path))

    def test_resolves_head(self, tmp_path):
        _init_repo(tmp_path)
        sha = _resolve_commit_hash("HEAD", repo_dir=str(tmp_path))
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    def test_resolves_tag(self, tmp_path):
        _init_repo(tmp_path)
        head_sha = _resolve_commit_hash("HEAD", repo_dir=str(tmp_path))
        tag_sha = _resolve_commit_hash("v1", repo_dir=str(tmp_path))
        assert head_sha == tag_sha

    def test_resolves_branch(self, tmp_path):
        _init_repo(tmp_path)
        head_sha = _resolve_commit_hash("HEAD", repo_dir=str(tmp_path))
        branch_sha = _resolve_commit_hash("main", repo_dir=str(tmp_path))
        assert head_sha == branch_sha

    def test_unknown_ref_errors(self, tmp_path):
        _init_repo(tmp_path)
        with pytest.raises(SystemExit) as exc:
            _resolve_commit_hash("no-such-ref", repo_dir=str(tmp_path))
        assert "no-such-ref" in str(exc.value)

    def test_outside_repo_errors(self, tmp_path):
        with pytest.raises(SystemExit):
            _resolve_commit_hash("HEAD", repo_dir=str(tmp_path))
