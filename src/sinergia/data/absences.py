"""Tabela de afastamentos: o registro estruturado criado pelo Agente 2."""

import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from sinergia.core.domain import AbsenceStatus, DocumentType
from sinergia.core.errors import NotFoundError
from sinergia.data.database import Database

_JSON_COLUMNS = ("violated_rules", "field_confidence")
_OPEN_STATUSES = (AbsenceStatus.PENDING.value, AbsenceStatus.HUMAN_REVIEW.value)
_COUNTED_STATUSES = (
    AbsenceStatus.VALID.value,
    AbsenceStatus.PENDING.value,
    AbsenceStatus.HUMAN_REVIEW.value,
)


class Absence(BaseModel):
    """Um afastamento, com a situação da validação e da revisão humana."""

    protocol: str
    session_id: str
    employee_id: str | None = None
    employee_name: str | None = None
    document_type: DocumentType | None = None
    issue_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    days: int | None = None
    doctor_name: str | None = None
    crm_number: str | None = None
    crm_uf: str | None = None
    crm_status: str | None = None
    signed: bool | None = None
    cid: str | None = None
    status: AbsenceStatus
    violated_rules: list[str] = Field(default_factory=list)
    field_confidence: dict[str, float] = Field(default_factory=dict)
    extraction_method: str
    rules_version: str
    reviewed_by: str | None = None
    review_decision: str | None = None
    review_note: str | None = None
    updated_at: datetime

    @property
    def last_day(self) -> date | None:
        """Último dia do afastamento (o próprio início, se não houver fim)."""
        return self.end_date or self.start_date


class AbsenceRepository:
    """Persistência dos afastamentos e das correções feitas na revisão humana."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def save(self, absence: Absence) -> None:
        """Insere ou substitui o registro do protocolo."""
        data = _to_row(absence)
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self._db.connect() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO absences ({columns}) VALUES ({marks})",
                tuple(data.values()),
            )

    def get(self, protocol: str) -> Absence:
        """Busca o afastamento de um protocolo."""
        rows = self._query("SELECT * FROM absences WHERE protocol = ?", (protocol,))
        if not rows:
            raise NotFoundError(f"Afastamento não encontrado: {protocol}")
        return rows[0]

    def open_reviews(self) -> list[Absence]:
        """Casos aguardando revisão humana, do mais antigo para o mais novo."""
        marks = ", ".join("?" for _ in _OPEN_STATUSES)
        sql = f"SELECT * FROM absences WHERE status IN ({marks}) ORDER BY updated_at"
        return self._query(sql, _OPEN_STATUSES)

    def for_employee(self, employee_id: str, exclude_protocol: str) -> list[Absence]:
        """Afastamentos vigentes ou em análise do colaborador, exceto o protocolo atual."""
        marks = ", ".join("?" for _ in _COUNTED_STATUSES)
        sql = (
            f"SELECT * FROM absences WHERE employee_id = ? AND protocol != ?"
            f" AND status IN ({marks}) ORDER BY start_date"
        )
        return self._query(sql, (employee_id, exclude_protocol, *_COUNTED_STATUSES))

    def add_feedback(
        self, protocol: str, field: str, extracted: Any, corrected: Any, reviewer: str, at: datetime
    ) -> None:
        """Guarda uma correção humana como exemplo para melhorar a extração."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO extraction_feedback (protocol, field, extracted, corrected, reviewer,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (protocol, field, _text(extracted), _text(corrected), reviewer, at.isoformat()),
            )

    def feedback_count(self, protocol: str) -> int:
        """Quantas correções humanas o protocolo recebeu."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM extraction_feedback WHERE protocol = ?", (protocol,)
            ).fetchone()
        return int(row[0])

    def _query(self, sql: str, params: tuple[Any, ...]) -> list[Absence]:
        """Executa uma consulta e converte as linhas em ``Absence``."""
        with self._db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_from_row(dict(row)) for row in rows]


def _to_row(absence: Absence) -> dict[str, Any]:
    """Serializa o modelo nas colunas da tabela."""
    data = absence.model_dump(mode="json")
    for column in _JSON_COLUMNS:
        data[column] = json.dumps(data[column])
    return data


def _from_row(row: dict[str, Any]) -> Absence:
    """Converte uma linha do banco em ``Absence``."""
    for column in _JSON_COLUMNS:
        row[column] = json.loads(row[column])
    return Absence.model_validate(row)


def _text(value: Any) -> str | None:
    """Representa um valor de campo como texto, para o histórico de correções."""
    return None if value is None else str(value)
