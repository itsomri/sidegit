"""Tests for /api/records endpoints."""

# Three canonical SHA-1 commit_hashes (40 lowercase hex chars each).
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "1234567890abcdef" * 2 + "1234567890abcdef"[:8]  # 40 hex chars


def _create(client, commit_hash=SHA_A, **kwargs):
    return client.post("/api/records", json={"commit_hash": commit_hash, **kwargs})


class TestCreateRecord:
    def test_valid(self, client):
        res = _create(client, commit_hash=SHA_A)
        assert res.status_code == 201
        body = res.get_json()
        assert body["commit_hash"] == SHA_A
        assert "id" in body
        assert body["data"] is None
        assert body["tags"] is None

    def test_missing_commit_hash(self, client):
        res = client.post("/api/records", json={})
        assert res.status_code == 400
        assert "commit_hash" in res.get_json()["error"]

    def test_empty_commit_hash_rejected(self, client):
        res = client.post("/api/records", json={"commit_hash": ""})
        assert res.status_code == 400

    def test_with_data_and_tags(self, client):
        res = _create(client, data={"latency_ms": 12.3}, tags={"env": "ci"})
        body = res.get_json()
        assert body["data"] == {"latency_ms": 12.3}
        assert body["tags"] == {"env": "ci"}

    def test_explicit_id(self, client):
        res = _create(client, id="my-id")
        assert res.get_json()["id"] == "my-id"

    def test_sha256_accepted(self, client):
        sha256 = "f" * 64
        res = _create(client, commit_hash=sha256)
        assert res.status_code == 201
        assert res.get_json()["commit_hash"] == sha256


class TestCommitHashValidation:
    """Server enforces canonical git SHA format on writes."""

    def test_rejects_short_sha(self, client):
        res = _create(client, commit_hash="abc123")
        assert res.status_code == 400
        assert "canonical" in res.get_json()["error"]

    def test_rejects_ref_name(self, client):
        for ref in ["HEAD", "main", "v1.0", "feature/x"]:
            assert _create(client, commit_hash=ref).status_code == 400

    def test_rejects_uppercase(self, client):
        res = _create(client, commit_hash="A" * 40)
        assert res.status_code == 400

    def test_rejects_non_hex(self, client):
        res = _create(client, commit_hash="g" * 40)
        assert res.status_code == 400

    def test_rejects_wrong_length(self, client):
        # 39, 41, 63, 65 — neither SHA-1 nor SHA-256 length
        for length in (39, 41, 63, 65):
            res = _create(client, commit_hash="a" * length)
            assert res.status_code == 400, f"length {length} should be rejected"

    def test_rejects_non_string(self, client):
        res = client.post("/api/records", json={"commit_hash": 12345})
        assert res.status_code == 400


class TestListRecords:
    def test_empty(self, client):
        res = client.get("/api/records")
        assert res.status_code == 200
        assert res.get_json() == []

    def test_filter_by_commit_hash(self, client):
        _create(client, commit_hash=SHA_A)
        _create(client, commit_hash=SHA_B)
        res = client.get(f"/api/records?commit_hash={SHA_A}")
        body = res.get_json()
        assert len(body) == 1
        assert body[0]["commit_hash"] == SHA_A

    def test_filter_by_tag(self, client):
        _create(client, commit_hash=SHA_A, tags={"env": "prod"})
        _create(client, commit_hash=SHA_B, tags={"env": "ci"})
        res = client.get("/api/records?tag=env:prod")
        body = res.get_json()
        assert len(body) == 1
        assert body[0]["tags"]["env"] == "prod"

    def test_tag_no_match(self, client):
        _create(client, commit_hash=SHA_A, tags={"env": "prod"})
        res = client.get("/api/records?tag=env:staging")
        assert res.get_json() == []


class TestGetRecord:
    def test_found(self, client):
        rid = _create(client).get_json()["id"]
        res = client.get(f"/api/records/{rid}")
        assert res.status_code == 200
        body = res.get_json()
        assert body["id"] == rid
        assert body["blobs"] == []

    def test_not_found(self, client):
        res = client.get("/api/records/no-such-id")
        assert res.status_code == 404


class TestDeleteRecord:
    def test_deletes_record(self, client):
        rid = _create(client).get_json()["id"]
        assert client.delete(f"/api/records/{rid}").status_code == 200
        assert client.get(f"/api/records/{rid}").status_code == 404

    def test_not_found(self, client):
        assert client.delete("/api/records/nope").status_code == 404
