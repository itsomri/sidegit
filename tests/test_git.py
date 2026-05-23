"""Tests for /api/git/* endpoints."""
import subprocess

import git
import pytest

from sidegit.app import create_app


def _make_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo_dir, check=True)
    (repo_dir / "f.txt").write_text("a")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "first"], cwd=repo_dir, check=True)
    (repo_dir / "f.txt").write_text("b")
    subprocess.run(["git", "commit", "-aq", "-m", "second"], cwd=repo_dir, check=True)
    subprocess.run(["git", "tag", "v1"], cwd=repo_dir, check=True)
    return git.Repo(str(repo_dir))


@pytest.fixture
def repo_client(tmp_path):
    repo = _make_repo(tmp_path)
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "BLOB_STORAGE_DIR": str(blob_dir),
        "GIT_REPO": repo,
    })
    return app.test_client()


class TestGitWithoutRepo:
    def test_refs_returns_404(self, client):
        res = client.get("/api/git/refs")
        assert res.status_code == 404

    def test_log_returns_404(self, client):
        res = client.get("/api/git/log")
        assert res.status_code == 404


class TestGitWithRepo:
    def test_refs(self, repo_client):
        res = repo_client.get("/api/git/refs")
        assert res.status_code == 200
        body = res.get_json()
        assert any(b["name"] == "main" for b in body["branches"])
        assert any(t["name"] == "v1" for t in body["tags"])
        assert body["head"]["name"] == "main"

    def test_log_default_ref(self, repo_client):
        res = repo_client.get("/api/git/log")
        assert res.status_code == 200
        body = res.get_json()
        assert len(body) == 2
        assert body[0]["message"] == "second"

    def test_log_limit(self, repo_client):
        res = repo_client.get("/api/git/log?limit=1")
        assert len(res.get_json()) == 1

    def test_log_bad_ref(self, repo_client):
        res = repo_client.get("/api/git/log?ref=no-such-branch")
        assert res.status_code == 404
