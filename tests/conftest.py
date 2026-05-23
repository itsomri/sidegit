import pytest

from sidegit.app import create_app


@pytest.fixture
def app(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    return create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "BLOB_STORAGE_DIR": str(blob_dir),
        "GIT_REPO": None,
    })


@pytest.fixture
def client(app):
    return app.test_client()
