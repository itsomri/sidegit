"""Tests for blob upload, download, and delete."""
import io
import os

_DEFAULT_SHA = "a" * 40


def _create_record(client, commit_hash=_DEFAULT_SHA):
    return client.post("/api/records", json={"commit_hash": commit_hash}).get_json()["id"]


def _upload(client, record_id, content=b"hello", name="test.txt", **form):
    return client.post(
        f"/api/records/{record_id}/blobs",
        content_type="multipart/form-data",
        data={"file": (io.BytesIO(content), name), **form},
    )


class TestUploadBlob:
    def test_valid(self, client):
        rid = _create_record(client)
        res = _upload(client, rid, content=b"hi", name="a.txt")
        assert res.status_code == 201
        body = res.get_json()
        assert body["name"] == "a.txt"
        assert body["size_bytes"] == 2
        assert body["record_id"] == rid

    def test_form_name_overrides_filename(self, client):
        rid = _create_record(client)
        res = client.post(
            f"/api/records/{rid}/blobs",
            content_type="multipart/form-data",
            data={"file": (io.BytesIO(b"x"), "uploaded.txt"), "name": "preferred.txt"},
        )
        assert res.get_json()["name"] == "preferred.txt"

    def test_with_extra_json(self, client):
        rid = _create_record(client)
        res = _upload(client, rid, extra='{"phase":"build"}')
        assert res.get_json()["extra"] == {"phase": "build"}

    def test_invalid_extra_json(self, client):
        rid = _create_record(client)
        res = _upload(client, rid, extra="{not json}")
        assert res.status_code == 400

    def test_record_not_found(self, client):
        res = _upload(client, "no-such-record")
        assert res.status_code == 404

    def test_no_file_part(self, client):
        rid = _create_record(client)
        res = client.post(f"/api/records/{rid}/blobs",
                          content_type="multipart/form-data", data={})
        assert res.status_code == 400


class TestDownloadBlob:
    def test_serves_content(self, client):
        rid = _create_record(client)
        bid = _upload(client, rid, content=b"payload-bytes").get_json()["id"]
        res = client.get(f"/api/blobs/{bid}")
        assert res.status_code == 200
        assert res.data == b"payload-bytes"

    def test_not_found(self, client):
        assert client.get("/api/blobs/no-such").status_code == 404


class TestDeleteBlob:
    def test_deletes_db_and_file(self, client, app):
        rid = _create_record(client)
        bid = _upload(client, rid, content=b"x").get_json()["id"]
        # File exists before delete
        storage_dir = app.config["BLOB_STORAGE_DIR"]
        assert len(os.listdir(storage_dir)) == 1
        assert client.delete(f"/api/blobs/{bid}").status_code == 200
        assert client.get(f"/api/blobs/{bid}").status_code == 404
        assert os.listdir(storage_dir) == []

    def test_not_found(self, client):
        assert client.delete("/api/blobs/no-such").status_code == 404


class TestRecordIncludesBlobs:
    def test_get_record_lists_blobs(self, client):
        rid = _create_record(client)
        _upload(client, rid, content=b"a", name="a.txt")
        _upload(client, rid, content=b"bb", name="b.txt")
        body = client.get(f"/api/records/{rid}").get_json()
        assert len(body["blobs"]) == 2
        assert {b["name"] for b in body["blobs"]} == {"a.txt", "b.txt"}

    def test_delete_record_cascades_blobs(self, client, app):
        rid = _create_record(client)
        _upload(client, rid, content=b"x")
        storage_dir = app.config["BLOB_STORAGE_DIR"]
        assert len(os.listdir(storage_dir)) == 1
        client.delete(f"/api/records/{rid}")
        assert os.listdir(storage_dir) == []
