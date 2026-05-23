"""Blob storage backends. Local filesystem or S3, selected by app config."""
from __future__ import annotations

import os
import shutil
import uuid
from typing import BinaryIO

from flask import current_app, redirect, send_from_directory
from werkzeug.utils import secure_filename


class LocalStorage:
    """Stores blobs under a single directory. `storage_ref` is the filename only."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def save(self, fileobj: BinaryIO, name: str) -> tuple[str, int]:
        safe = secure_filename(name) or "blob"
        ref = f"{uuid.uuid4()}_{safe}"
        path = os.path.join(self.root, ref)
        with open(path, "wb") as dst:
            shutil.copyfileobj(fileobj, dst)
        return ref, os.path.getsize(path)

    def serve(self, ref: str, mime_type: str | None, download_name: str):
        if "/" in ref or "\\" in ref or ref.startswith("."):
            return {"error": "Invalid storage ref"}, 400
        return send_from_directory(
            self.root, ref, as_attachment=True,
            mimetype=mime_type, download_name=download_name,
        )

    def delete(self, ref: str) -> None:
        path = os.path.join(self.root, ref)
        if os.path.abspath(path).startswith(self.root) and os.path.exists(path):
            os.remove(path)


class S3Storage:
    """Stores blobs in an S3 bucket. `storage_ref` is the object key."""

    def __init__(self, bucket: str, endpoint_url: str | None = None, prefix: str = "blobs/"):
        import boto3
        self.bucket = bucket
        self.prefix = prefix
        self.client = boto3.client("s3", endpoint_url=endpoint_url)

    def save(self, fileobj: BinaryIO, name: str) -> tuple[str, int]:
        safe = secure_filename(name) or "blob"
        key = f"{self.prefix}{uuid.uuid4()}_{safe}"
        fileobj.seek(0, os.SEEK_END)
        size = fileobj.tell()
        fileobj.seek(0)
        self.client.upload_fileobj(fileobj, self.bucket, key)
        return key, size

    def serve(self, ref: str, mime_type: str | None, download_name: str):
        url = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": ref},
            ExpiresIn=3600,
        )
        return redirect(url)

    def delete(self, ref: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=ref)


def get_storage():
    """Return the configured storage backend for the current Flask app."""
    return current_app.config["STORAGE"]


def make_storage_from_config(config):
    """Build a storage backend from app config dict-like."""
    bucket = config.get("S3_BUCKET")
    if bucket:
        return S3Storage(bucket=bucket, endpoint_url=config.get("S3_ENDPOINT_URL"))
    return LocalStorage(config["BLOB_STORAGE_DIR"])
