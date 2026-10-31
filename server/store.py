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
                needs_upgrade = source.execute("SELECT COUNT(*) FROM migrations WHERE version IN (5,6)").fetchone()[0] != 2
                if needs_upgrade:
                    backups = self.directory / "backups"
                    backups.mkdir(mode=0o700, exist_ok=True)
                    backup = backups / ("before-upgrade-" + str(time.time_ns()) + ".sqlite3")
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
            # Seeding by display name on every start recreated a client after renaming it.
            if con.execute('SELECT COUNT(*) FROM clients').fetchone()[0] == 0:
                for name in ("GZI", "Dangote", "CHI"):
                    con.execute("INSERT INTO clients(name,created_at) VALUES(?,?)", (name, time.time()))
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
                CREATE TABLE IF NOT EXISTS report_updates(
                    id INTEGER PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
                    batch_id TEXT NOT NULL, source_row INTEGER NOT NULL, effective_record TEXT NOT NULL,
                    created_at REAL NOT NULL, UNIQUE(batch_id,source_row),
                    FOREIGN KEY(batch_id,source_row) REFERENCES import_rows(batch_id,source_row));
                CREATE TABLE IF NOT EXISTS shipment_aliases(
                    shipment_id INTEGER PRIMARY KEY REFERENCES shipments(id),
                    canonical_id INTEGER NOT NULL REFERENCES shipments(id),
                    reason TEXT NOT NULL, created_at REAL NOT NULL);
                INSERT OR IGNORE INTO migrations VALUES(4);
                CREATE TABLE IF NOT EXISTS departments(
                    id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at REAL NOT NULL);
            """)
            con.execute('BEGIN IMMEDIATE')
            if not con.execute('SELECT 1 FROM migrations WHERE version=5').fetchone():
                con.execute("INSERT OR IGNORE INTO departments(name,created_at) VALUES('FMCG 1',?)", (time.time(),))
                department = con.execute("SELECT id FROM departments WHERE name='FMCG 1'").fetchone()[0]
                con.execute('ALTER TABLE clients ADD COLUMN department_id INTEGER REFERENCES departments(id)')
                con.execute('ALTER TABLE clients ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK(hidden IN (0,1))')
                con.execute("ALTER TABLE clients ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
                con.execute('ALTER TABLE clients ADD COLUMN revision INTEGER NOT NULL DEFAULT 1')
                con.execute('ALTER TABLE clients ADD COLUMN import_profile TEXT')
                con.execute('UPDATE clients SET department_id=?', (department,))
                con.execute("""UPDATE clients SET import_profile=CASE UPPER(TRIM(name))
                    WHEN 'GZI' THEN 'gzi-header-v2' WHEN 'CHI' THEN 'chi-header-v1' END""")
                self.audit(con, 'client_departments_initialised', {
                    'department_id': department, 'department_name': 'FMCG 1',
                    'client_ids': [r[0] for r in con.execute('SELECT id FROM clients ORDER BY id')],
                    'reason': 'Initial department assignment requested by the owner; existing identities and jobs retained.'
                }, actor='migration')
                con.execute('INSERT INTO migrations VALUES(5)')
            con.executescript("""
                CREATE TABLE IF NOT EXISTS tracking_configs(
                    shipment_id INTEGER PRIMARY KEY REFERENCES shipments(id),
                    revision INTEGER NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tracking_checks(
                    id TEXT PRIMARY KEY, shipment_id INTEGER NOT NULL REFERENCES shipments(id),
                    config_revision INTEGER NOT NULL, started_at REAL NOT NULL, ended_at REAL,
                    status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '',
                    observation TEXT, raw_text TEXT, changes TEXT, review TEXT);
                CREATE INDEX IF NOT EXISTS tracking_checks_job ON tracking_checks(shipment_id,started_at);
                INSERT OR IGNORE INTO migrations VALUES(6);
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
