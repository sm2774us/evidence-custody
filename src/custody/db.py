"""SQLite persistence (dev/reference). Production swaps in PostgreSQL with the same schema
and REVOKE UPDATE/DELETE on audit tables; the triggers below are defense in depth."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

_IMMUTABLE = ("audit_log", "audit_checkpoints", "evidence", "derivatives")


def _triggers() -> str:
    out = []
    for t in _IMMUTABLE:
        for op in ("UPDATE", "DELETE"):
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                f"BEGIN SELECT RAISE(ABORT, '{t} is append-only'); END;"
            )
    return "\n".join(out)


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices(
  device_id TEXT PRIMARY KEY, public_key TEXT NOT NULL, officer_id TEXT NOT NULL,
  agency_id TEXT NOT NULL, status TEXT NOT NULL, registered_by TEXT NOT NULL,
  activated_by TEXT, registered_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS revoked_tokens(jti TEXT PRIMARY KEY, revoked_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  session_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, agency_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL, manifest_hash TEXT NOT NULL, manifest_json TEXT NOT NULL,
  sequence_no INTEGER NOT NULL, state TEXT NOT NULL, evidence_id TEXT,
  failure_reason TEXT, retry_authorized INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  UNIQUE(device_id, idempotency_key));
CREATE UNIQUE INDEX IF NOT EXISTS ux_active_seq ON sessions(device_id, sequence_no)
  WHERE state NOT IN ('expired', 'quarantined');
CREATE TABLE IF NOT EXISTS chunks(
  session_id TEXT NOT NULL, idx INTEGER NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
  PRIMARY KEY(session_id, idx));
CREATE TABLE IF NOT EXISTS evidence(
  evidence_id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE, agency_id TEXT NOT NULL,
  device_id TEXT NOT NULL, officer_id TEXT NOT NULL, case_id TEXT, sequence_no INTEGER NOT NULL,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, media_type TEXT NOT NULL,
  storage_key TEXT NOT NULL, version_id TEXT NOT NULL, retention_until_ms INTEGER NOT NULL,
  captured_at_ms INTEGER NOT NULL, received_at_ms INTEGER NOT NULL, future_skew_ms INTEGER,
  receipt_json TEXT NOT NULL, receipt_sig TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_evidence_device ON evidence(device_id, sequence_no);
CREATE TABLE IF NOT EXISTS derivatives(
  derivative_id TEXT PRIMARY KEY, parent_evidence_id TEXT NOT NULL, parent_sha256 TEXT NOT NULL,
  kind TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, media_type TEXT NOT NULL,
  storage_key TEXT NOT NULL, params_json TEXT NOT NULL, created_by TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS legal_holds(
  hold_id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL, case_ref TEXT NOT NULL,
  reason TEXT NOT NULL, status TEXT NOT NULL, requested_by TEXT NOT NULL, approved_by TEXT,
  released_by TEXT, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS alerts(
  alert_id TEXT PRIMARY KEY, ts_ms INTEGER NOT NULL, kind TEXT NOT NULL, severity TEXT NOT NULL,
  object_id TEXT, detail_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  acked_by TEXT, acked_at_ms INTEGER);
CREATE TABLE IF NOT EXISTS audit_log(
  seq INTEGER PRIMARY KEY, ts_ms INTEGER NOT NULL, actor TEXT NOT NULL, actor_role TEXT NOT NULL,
  action TEXT NOT NULL, object_type TEXT NOT NULL, object_id TEXT NOT NULL, object_version TEXT,
  source_ip TEXT, request_id TEXT, detail_json TEXT NOT NULL,
  prev_hash TEXT NOT NULL, entry_hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_audit_object ON audit_log(object_id);
CREATE INDEX IF NOT EXISTS ix_audit_actor ON audit_log(actor, ts_ms);
CREATE TABLE IF NOT EXISTS audit_checkpoints(
  seq INTEGER PRIMARY KEY, entry_hash TEXT NOT NULL, ts_ms INTEGER NOT NULL,
  key_id TEXT NOT NULL, signature TEXT NOT NULL);
""" + _triggers()


class Database:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction. State changes and their audit rows commit atomically."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def query(self, sql: str, args: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, args).fetchall()

    def one(self, sql: str, args: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    def raw(self) -> sqlite3.Connection:
        """Test hook: direct handle to simulate an attacker with database access."""
        return self._conn
