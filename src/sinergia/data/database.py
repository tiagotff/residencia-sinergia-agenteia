"""Conexão e esquema do banco SQLite de negócio."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS intakes (
    protocol       TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    employee_id    TEXT,
    channel        TEXT NOT NULL,
    document_type  TEXT,
    absence_start  TEXT,
    received_at    TEXT NOT NULL,
    status         TEXT NOT NULL,
    late_delivery  INTEGER NOT NULL DEFAULT 0,
    file_path      TEXT,
    file_sha256    TEXT,
    mime_type      TEXT,
    original_name  TEXT,
    attempts       INTEGER NOT NULL,
    rules_version  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pendencies (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol     TEXT NOT NULL REFERENCES intakes(protocol),
    kind         TEXT NOT NULL,
    target_area  TEXT NOT NULL,
    rule_id      TEXT,
    status       TEXT NOT NULL DEFAULT 'aberta',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS absences (
    protocol           TEXT PRIMARY KEY REFERENCES intakes(protocol),
    session_id         TEXT NOT NULL,
    employee_id        TEXT,
    employee_name      TEXT,
    document_type      TEXT,
    issue_date         TEXT,
    start_date         TEXT,
    end_date           TEXT,
    days               INTEGER,
    doctor_name        TEXT,
    crm_number         TEXT,
    crm_uf             TEXT,
    crm_status         TEXT,
    signed             INTEGER,
    cid                TEXT,
    status             TEXT NOT NULL,
    violated_rules     TEXT NOT NULL,
    field_confidence   TEXT NOT NULL,
    extraction_method  TEXT NOT NULL,
    rules_version      TEXT NOT NULL,
    reviewed_by        TEXT,
    review_decision    TEXT,
    review_note        TEXT,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vacations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id  TEXT NOT NULL,
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    source       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (employee_id, start_date, end_date)
);

CREATE TABLE IF NOT EXISTS extraction_feedback (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol     TEXT NOT NULL REFERENCES intakes(protocol),
    field        TEXT NOT NULL,
    extracted    TEXT,
    corrected    TEXT,
    reviewer     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at    TEXT NOT NULL,
    actor          TEXT NOT NULL,
    action         TEXT NOT NULL,
    reference      TEXT NOT NULL,
    rule_ids       TEXT NOT NULL,
    rules_version  TEXT NOT NULL,
    details        TEXT NOT NULL
);
"""


class Database:
    """Abre conexões curtas com o SQLite; cada operação fecha a sua."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> None:
        """Cria a pasta e as tabelas, se ainda não existirem."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Abre uma conexão com commit ao final e rollback em caso de erro."""
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
