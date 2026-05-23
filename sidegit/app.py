"""sidegit Flask app — store records and blobs alongside git commits."""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import uuid

import git
from flask import Blueprint, Flask, current_app, jsonify, request
from flask_sqlalchemy import SQLAlchemy

from sidegit.storage import get_storage, make_storage_from_config

logger = logging.getLogger("sidegit")

db = SQLAlchemy()


# ── Models ──────────────────────────────────────────────────────────────────

class Record(db.Model):
    __tablename__ = "records"
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    commit_hash = db.Column(db.String(64), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    data = db.Column(db.JSON)
    tags = db.Column(db.JSON)

    blobs = db.relationship("Blob", backref="record", lazy=True, cascade="all, delete-orphan")

    def to_dict(self, include_blobs: bool = False):
        d = {
            "id": self.id,
            "commit_hash": self.commit_hash,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "data": self.data,
            "tags": self.tags,
        }
        if include_blobs:
            d["blobs"] = [b.to_dict() for b in self.blobs]
        return d


class Blob(db.Model):
    __tablename__ = "blobs"
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    record_id = db.Column(db.String(36), db.ForeignKey("records.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    storage_ref = db.Column(db.String(512), nullable=False)
    mime_type = db.Column(db.String(100))
    size_bytes = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.datetime.now(datetime.UTC))
    extra = db.Column(db.JSON)

    def to_dict(self):
        return {
            "id": self.id,
            "record_id": self.record_id,
            "name": self.name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "extra": self.extra,
        }


# ── Validation ──────────────────────────────────────────────────────────────

_SHA_RE = re.compile(r"^[0-9a-f]{40}$|^[0-9a-f]{64}$")


def _validate_commit_hash(value: str | None) -> str | None:
    """Return an error message if `value` is not a canonical git object name."""
    if not value:
        return "commit_hash is required"
    if not isinstance(value, str) or not _SHA_RE.match(value):
        return (
            "commit_hash must be a canonical git object name: "
            "40 lowercase hex chars (SHA-1) or 64 (SHA-256). "
            "Resolve refs with `git rev-parse <ref>` before posting."
        )
    return None


# ── Blueprint ───────────────────────────────────────────────────────────────

bp = Blueprint("sidegit", __name__)


@bp.route("/api/records", methods=["GET", "POST"])
def records():
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        err = _validate_commit_hash(body.get("commit_hash"))
        if err:
            return jsonify({"error": err}), 400
        rec = Record(
            id=body.get("id", str(uuid.uuid4())),
            commit_hash=body["commit_hash"],
            data=body.get("data"),
            tags=body.get("tags"),
        )
        db.session.add(rec)
        db.session.commit()
        return jsonify(rec.to_dict()), 201

    q = Record.query
    commit = request.args.get("commit_hash")
    if commit:
        q = q.filter_by(commit_hash=commit)
    rows = q.order_by(Record.timestamp.desc()).all()

    tag_filter = request.args.get("tag")
    if tag_filter:
        key, _, value = tag_filter.partition(":")
        rows = [r for r in rows if r.tags and str(r.tags.get(key)) == value]

    return jsonify([r.to_dict() for r in rows])


@bp.route("/api/records/<record_id>", methods=["GET", "DELETE"])
def record(record_id):
    rec = db.session.get(Record, record_id)
    if not rec:
        return jsonify({"error": "Record not found"}), 404

    if request.method == "DELETE":
        storage = get_storage()
        for blob in rec.blobs:
            try:
                storage.delete(blob.storage_ref)
            except Exception as e:
                logger.warning("Failed to delete blob %s: %s", blob.id, e)
        db.session.delete(rec)
        db.session.commit()
        return jsonify({"ok": True})

    return jsonify(rec.to_dict(include_blobs=True))


@bp.route("/api/records/<record_id>/blobs", methods=["POST"])
def upload_blob(record_id):
    rec = db.session.get(Record, record_id)
    if not rec:
        return jsonify({"error": "Record not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No selected file"}), 400

    name = request.form.get("name") or f.filename
    mime_type = request.form.get("mime_type") or f.mimetype or "application/octet-stream"
    extra_str = request.form.get("extra")
    try:
        extra = json.loads(extra_str) if extra_str else None
    except json.JSONDecodeError:
        return jsonify({"error": "extra must be valid JSON"}), 400

    ref, size = get_storage().save(f, name)
    blob = Blob(
        record_id=record_id,
        name=name,
        storage_ref=ref,
        mime_type=mime_type,
        size_bytes=size,
        extra=extra,
    )
    db.session.add(blob)
    db.session.commit()
    return jsonify(blob.to_dict()), 201


@bp.route("/api/blobs/<blob_id>", methods=["GET", "DELETE"])
def blob(blob_id):
    b = db.session.get(Blob, blob_id)
    if not b:
        return jsonify({"error": "Blob not found"}), 404

    if request.method == "DELETE":
        try:
            get_storage().delete(b.storage_ref)
        except Exception as e:
            logger.warning("Failed to delete blob file %s: %s", b.id, e)
        db.session.delete(b)
        db.session.commit()
        return jsonify({"ok": True})

    return get_storage().serve(b.storage_ref, b.mime_type, b.name)


# ── Git endpoints ───────────────────────────────────────────────────────────

@bp.route("/api/git/refs")
def git_refs():
    repo = _repo()
    if not repo:
        return jsonify({"error": "No git repository configured"}), 404
    try:
        try:
            head_name = repo.head.ref.name
        except TypeError:
            head_name = f"detached @ {repo.head.commit.hexsha[:12]}"
        return jsonify({
            "branches": sorted(
                [{"name": b.name, "sha": b.commit.hexsha} for b in repo.branches],
                key=lambda x: x["name"],
            ),
            "tags": sorted(
                [{"name": t.name, "sha": t.commit.hexsha} for t in repo.tags],
                key=lambda x: x["name"],
            ),
            "head": {"name": head_name, "sha": repo.head.commit.hexsha},
        })
    except Exception as e:
        logger.exception("git_refs failed")
        return jsonify({"error": "Error reading git repo", "details": str(e)}), 500


@bp.route("/api/git/log")
def git_log():
    repo = _repo()
    if not repo:
        return jsonify({"error": "No git repository configured"}), 404
    try:
        default_ref = repo.head.ref.name
    except TypeError:
        default_ref = repo.head.commit.hexsha
    ref = request.args.get("ref", default_ref)
    limit = request.args.get("limit", 100, type=int)
    try:
        out = repo.git.log(ref, f"--max-count={limit}", "--format=%H|%P|%an|%cI|%s")
    except git.exc.GitCommandError:
        return jsonify({"error": f"Ref '{ref}' not found"}), 404

    commits = []
    for line in out.splitlines():
        if not line:
            continue
        try:
            sha, parents, author, date, subject = line.split("|", 4)
            commits.append({
                "sha": sha,
                "parent_shas": parents.split() if parents.strip() else [],
                "message": subject,
                "author": author,
                "date": date,
            })
        except ValueError:
            logger.warning("Failed to parse commit line: %s", line)
    return jsonify(commits)


def _repo():
    return current_app.config.get("GIT_REPO")


# ── App factory ─────────────────────────────────────────────────────────────

def create_app(config: dict | None = None) -> Flask:
    """Build a Flask app.

    `config` may be:
      - None: load layered config from file/env (production path).
      - A flat Flask-config dict (typically used by tests; must include
        BLOB_STORAGE_DIR or a pre-built STORAGE).
    """
    app = Flask(__name__)
    if config is not None:
        app.config.update(config)
        if "BLOB_STORAGE_DIR" not in app.config and "STORAGE" not in app.config:
            raise RuntimeError("config must provide BLOB_STORAGE_DIR or STORAGE")
    else:
        from sidegit.config import load_config, to_flask_config
        cfg = load_config()
        flask_cfg = to_flask_config(cfg)
        os.makedirs(flask_cfg["SIDEGIT_DATA_DIR"], exist_ok=True)
        os.makedirs(flask_cfg["BLOB_STORAGE_DIR"], exist_ok=True)
        app.config.update(flask_cfg)

        repo_path = flask_cfg["SIDEGIT_REPO_DIR"]
        try:
            repo = git.Repo(repo_path, search_parent_directories=True)
            logger.info("Loaded git repo at %s (HEAD %s)",
                        repo.working_dir, repo.head.commit.hexsha[:12])
        except (git.InvalidGitRepositoryError, git.NoSuchPathError):
            logger.info("No git repo found at %s; /api/git/* will return 404", repo_path)
            repo = None
        app.config["GIT_REPO"] = repo

    if "STORAGE" not in app.config:
        app.config["STORAGE"] = make_storage_from_config(app.config)

    db.init_app(app)
    app.register_blueprint(bp)
    with app.app_context():
        db.create_all()
    return app
