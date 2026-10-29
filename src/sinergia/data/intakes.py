"""Tabela de entrada: uma linha por documento recebido, identificada pelo protocolo."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from sinergia.core.domain import CaseStatus, DocumentType
from sinergia.core.errors import NotFoundError
from sinergia.data.database import Database


class Intake(BaseModel):
    """Linha de entrada criada pelo Agente 1."""

    protocol: str
    session_id: str
    employee_id: str | None
    channel: str
    document_type: DocumentType | None
    absence_start: date | None
    received_at: datetime
    status: CaseStatus
    late_delivery: bool = False
    file_path: str | None = None
    file_sha256: str | None = None
    mime_type: str | None = None
    original_name: str | None = None
    attempts: int
    rules_version: str


class Pendency(BaseModel):
    """Pendência aberta para uma área (ex.: RH)."""

    protocol: str
    kind: str
    target_area: str
    rule_id: str | None
    status: str
    created_at: datetime


class IntakeRepository:
    """Persistência das linhas de entrada e das pendências."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, intake: Intake) -> None:
        """Insere uma nova linha de entrada."""
        data = intake.model_dump(mode="json")
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self._db.connect() as conn:
            conn.execute(f"INSERT INTO intakes ({columns}) VALUES ({marks})", tuple(data.values()))

    def get(self, protocol: str) -> Intake:
        """Busca uma linha pelo protocolo."""
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM intakes WHERE protocol = ?", (protocol,)).fetchone()
        if row is None:
            raise NotFoundError(f"Protocolo não encontrado: {protocol}")
        return Intake.model_validate(dict(row))

    def open_pendency(
        self, protocol: str, kind: str, target_area: str, rule_id: str | None, at: datetime
    ) -> None:
        """Abre uma pendência ligada ao protocolo."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO pendencies (protocol, kind, target_area, rule_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (protocol, kind, target_area, rule_id, at.isoformat()),
            )

    def pendencies_for(self, protocol: str) -> list[Pendency]:
        """Lista as pendências de um protocolo."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pendencies WHERE protocol = ? ORDER BY id", (protocol,)
            ).fetchall()
        return [Pendency.model_validate(_without_id(row)) for row in rows]


def _without_id(row: Any) -> dict[str, Any]:
    """Remove a chave técnica ``id`` de uma linha."""
    data = dict(row)
    data.pop("id", None)
    return data
