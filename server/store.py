"""Application storage, deliberately independent of Hermes runtime state."""

import contextlib
import json
import os
import sqlite3
import time
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "libra-test.sqlite3"
        if self.path.exists() and self.path.stat().st_size:
            # SQLite's backup API includes committed WAL pages; copying just the DB can lose imports.
            with sqlite3.connect(self.path) as source:
                needs_upgrade = not source.execute("SELECT 1 FROM migrations WHERE version=2").fetchone()
                if needs_upgrade:
                    backups = self.directory / "backups"
                    backups.mkdir(mode=0o700, exist_ok=True)
                    backup = backups / ("before-slice2-" + str(time.time_ns()) + ".sqlite3")
                    with sqlite3.connect(backup) as target:
                        source.backup(target)
                    backup.chmod(0o600)
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS clients(
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(
                    token_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS batches(
                    id TEXT PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
                    filename TEXT NOT NULL, sha256 TEXT NOT NULL, report_date TEXT,
                    created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'preview',
                    summary TEXT NOT NULL, mapping TEXT NOT NULL,
                    UNIQUE(client_id,sha256));
                CREATE TABLE IF NOT EXISTS import_rows(
                    batch_id TEXT NOT NULL REFERENCES batches(id), source_row INTEGER NOT NULL,
                    raw TEXT NOT NULL, record TEXT NOT NULL,
                    PRIMARY KEY(batch_id,source_row));
                CREATE TABLE IF NOT EXISTS shipments(
                    id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
                    batch_id TEXT NOT NULL REFERENCES batches(id), source_row INTEGER NOT NULL,
                    created_at REAL NOT NULL, UNIQUE(batch_id,source_row));
                CREATE TABLE IF NOT EXISTS audit(
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, detail TEXT NOT NULL);
                INSERT OR IGNORE INTO migrations VALUES(1);
            """)
            for name in ("GZI", "Dangote", "CHI"):
                con.execute("INSERT OR IGNORE INTO clients(name,created_at) VALUES(?,?)",
                            (name, time.time()))
            # v1 required an import for every job. Manual jobs have no source row.
            if con.execute("SELECT COUNT(*) FROM migrations WHERE version=2").fetchone()[0] == 0:
                con.execute("ALTER TABLE shipments RENAME TO shipments_v1")
                con.execute("""CREATE TABLE shipments(
                    id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL REFERENCES clients(id),
                    batch_id TEXT REFERENCES batches(id), source_row INTEGER,
                    created_at REAL NOT NULL, UNIQUE(batch_id,source_row))""")
                con.execute("INSERT INTO shipments SELECT * FROM shipments_v1")
                con.execute("DROP TABLE shipments_v1")
                con.execute("INSERT INTO migrations VALUES(2)")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS job_updates(
                    shipment_id INTEGER PRIMARY KEY REFERENCES shipments(id),
                    revision INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS movements(
                    id TEXT PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
                    kind TEXT NOT NULL, quantity INTEGER NOT NULL, date TEXT NOT NULL,
                    supersedes TEXT UNIQUE REFERENCES movements(id),
                    exception_reason TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS commands(
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, response TEXT NOT NULL);
                INSERT OR IGNORE INTO migrations VALUES(3);
            """)
        os.chmod(self.path, 0o600)

    @contextlib.contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def audit(self, con, action, detail, actor="owner"):
        con.execute("INSERT INTO audit(at,actor,action,detail) VALUES(?,?,?,?)",
                    (time.time(), actor, action, encode(detail)))
