"""Tests for the local storage backend (S3 backend is exercised via integration only)."""
import io
import os

from sidegit.storage import LocalStorage, make_storage_from_config


class TestLocalStorage:
    def test_save_and_read(self, tmp_path):
        s = LocalStorage(str(tmp_path))
        ref, size = s.save(io.BytesIO(b"hello"), "file.txt")
        assert size == 5
        # File landed inside the root
        assert os.path.isfile(os.path.join(str(tmp_path), ref))
        # Ref is just a filename, not a path
        assert "/" not in ref

    def test_delete(self, tmp_path):
        s = LocalStorage(str(tmp_path))
        ref, _ = s.save(io.BytesIO(b"x"), "f.txt")
        s.delete(ref)
        assert os.listdir(str(tmp_path)) == []

    def test_delete_missing_is_noop(self, tmp_path):
        LocalStorage(str(tmp_path)).delete("does-not-exist")  # no exception

    def test_filename_sanitized(self, tmp_path):
        s = LocalStorage(str(tmp_path))
        ref, _ = s.save(io.BytesIO(b"x"), "../../etc/passwd")
        # Sanitized: no path traversal in ref
        assert ".." not in ref
        assert "/" not in ref


class TestMakeStorageFromConfig:
    def test_local_when_no_s3(self, tmp_path):
        storage = make_storage_from_config({"BLOB_STORAGE_DIR": str(tmp_path)})
        assert isinstance(storage, LocalStorage)
