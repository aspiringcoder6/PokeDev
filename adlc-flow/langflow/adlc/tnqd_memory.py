"""Versioned project document memory; no synthesis, no cross-project reads, no Verify authority."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from datetime import datetime, timezone

class ProjectDocumentMemory:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS documents (scope TEXT, id TEXT, revision TEXT, body TEXT, digest TEXT, source TEXT, created TEXT, PRIMARY KEY(scope,id,revision))")
            db.execute("CREATE TABLE IF NOT EXISTS reads (id TEXT PRIMARY KEY, scope TEXT, document TEXT, revision TEXT, context TEXT, digest TEXT, created TEXT)")
    def publish(self, scope, identity, revision, body, source):
        if not body.strip() or len(body.encode()) > 128000:
            raise ValueError("TNQD_MEMORY_DOCUMENT_LIMIT")
        digest = hashlib.sha256(body.encode()).hexdigest()
        stamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest FROM documents WHERE scope=? AND id=? AND revision=?", (scope, identity, revision)).fetchone()
            if old and old[0] != digest:
                raise ValueError("TNQD_MEMORY_REVISION_CONFLICT")
            db.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?,?)", (scope, identity, revision, body, digest, source, stamp))
        return self.read(scope, identity, revision, "publication-check")
    def read(self, scope, identity, revision, caller_context):
        stamp = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT body,digest,source FROM documents WHERE scope=? AND id=? AND revision=?", (scope, identity, revision)).fetchone()
            if not row:
                raise ValueError("TNQD_MEMORY_DOCUMENT_NOT_FOUND")
            if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise ValueError("TNQD_MEMORY_DIGEST_MISMATCH")
            retrieval_id = str(uuid4())
            db.execute("INSERT INTO reads VALUES (?,?,?,?,?,?,?)", (retrieval_id, scope, identity, revision, caller_context, row[1], stamp))
        return {"document_id": identity, "revision": revision, "body": row[0], "sha256": row[1],
                "source_ref": row[2], "retrieval_id": retrieval_id, "retrieved_at": stamp,
                "caller_context_id": caller_context, "content_verified": True,
                "mode": "POKEDEV_PROJECT_DOCUMENT_STORE", "durable_graph_verified": False,
                "graph_ingestion": False, "verification_evidence": False}

    def latest(self, scope, identity, caller_context, verified_only=False):
        with sqlite3.connect(self.path) as db:
            row=db.execute("SELECT revision FROM documents WHERE scope=? AND id=?"+(" AND revision LIKE 'verified-%'" if verified_only else "")+" ORDER BY created DESC,rowid DESC LIMIT 1",(scope,identity)).fetchone()
        return self.read(scope,identity,row[0],caller_context) if row else None
