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
