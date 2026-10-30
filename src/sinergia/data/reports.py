"""Relatórios da crew de insights: rascunho até o médico do trabalho aprovar ou devolver."""

import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sinergia.core.errors import NotFoundError
from sinergia.data.database import Database

_JSON_COLUMNS = ("facts", "issues")


class ReportStatus(StrEnum):
    """Situação do relatório."""

    DRAFT = "rascunho"
    APPROVED = "aprovado"
    RETURNED = "devolvido"


class Report(BaseModel):
    """Relatório do período, com os fatos que o embasam e o que a conferência apontou."""

    period_start: date
    period_end: date
    status: ReportStatus = ReportStatus.DRAFT
    method: str
    content: str
    facts: dict[str, Any] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    rules_version: str


class StoredReport(Report):
    """Relatório gravado."""

    id: int
    created_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None
    note: str | None = None


class ReportRepository:
    """Persistência dos relatórios."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, report: Report, at: datetime) -> int:
        """Grava o relatório e devolve o id."""
        data = report.model_dump(mode="json")
        for column in _JSON_COLUMNS:
            data[column] = json.dumps(data[column], ensure_ascii=False)
        data["created_at"] = at.isoformat()
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self._db.connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO reports ({columns}) VALUES ({marks})", tuple(data.values())
            )
        return cursor.lastrowid or 0

    def get(self, report_id: int) -> StoredReport:
        """Um relatório pelo id."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Relatório não encontrado: {report_id}")
        return _from_row(dict(row))

    def recent(self, limit: int = 20) -> list[StoredReport]:
        """Relatórios mais recentes primeiro."""
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM reports ORDER BY id DESC LIMIT ?", (limit,))
            return [_from_row(dict(row)) for row in rows.fetchall()]

    def decide(
        self, report_id: int, status: ReportStatus, by: str, at: datetime, note: str | None
    ) -> None:
        """Registra a decisão do médico do trabalho."""
        with self._db.connect() as conn:
            conn.execute(
                "UPDATE reports SET status = ?, decided_by = ?, decided_at = ?, note = ?"
                " WHERE id = ?",
                (status.value, by, at.isoformat(), note, report_id),
            )


def _from_row(row: dict[str, Any]) -> StoredReport:
    """Converte uma linha do banco em ``StoredReport``."""
    for column in _JSON_COLUMNS:
        row[column] = json.loads(row[column])
    return StoredReport.model_validate(row)
