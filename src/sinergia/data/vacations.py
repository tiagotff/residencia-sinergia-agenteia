"""Férias registradas, usadas pela R07 (afastamento sobreposto a férias).

As férias vêm do sistema de RH/folha. Enquanto não há integração, entram por cadastro
manual (CLI/API) ou por importação de CSV exportado do sistema de folha.
"""

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from sinergia.core.dates import parse_date
from sinergia.data.database import Database

CSV_COLUMNS = ("employee_id", "start_date", "end_date")


class Vacation(BaseModel):
    """Período de férias de um colaborador."""

    employee_id: str
    start_date: date
    end_date: date
    source: str = "manual"

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _dates(cls, value: Any) -> Any:
        """Aceita DD/MM/AAAA e AAAA-MM-DD."""
        return parse_date(value) or value

    @model_validator(mode="after")
    def _ordered(self) -> "Vacation":
        """O fim das férias não pode ser anterior ao início."""
        if self.end_date < self.start_date:
            raise ValueError("O fim das férias é anterior ao início.")
        return self


class VacationRepository:
    """Persistência e importação das férias."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, vacation: Vacation, at: datetime) -> bool:
        """Grava o período; devolve False se ele já estava cadastrado."""
        with self._db.connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO vacations (employee_id, start_date, end_date, source,"
                " created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    vacation.employee_id,
                    vacation.start_date.isoformat(),
                    vacation.end_date.isoformat(),
                    vacation.source,
                    at.isoformat(),
                ),
            )
        return cursor.rowcount == 1

    def for_employee(self, employee_id: str) -> list[Vacation]:
        """Férias do colaborador, em ordem cronológica."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT employee_id, start_date, end_date, source FROM vacations"
                " WHERE employee_id = ? ORDER BY start_date",
                (employee_id,),
            ).fetchall()
        return [Vacation.model_validate(dict(row)) for row in rows]

    def import_csv(self, path: Path, at: datetime) -> int:
        """Importa um CSV com employee_id, start_date e end_date; devolve quantos entraram."""
        vacations = read_vacations_csv(path)
        return sum(self.add(vacation, at) for vacation in vacations)


def read_vacations_csv(path: Path) -> list[Vacation]:
    """Lê e valida todas as linhas antes de gravar qualquer uma."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=_delimiter(path))
        missing = set(CSV_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Colunas ausentes no CSV de férias: {sorted(missing)}")
        return [_row(number, row) for number, row in enumerate(reader, start=2)]


def _row(number: int, row: dict[str, str]) -> Vacation:
    """Converte uma linha do CSV, indicando a linha em caso de erro."""
    try:
        return Vacation(
            employee_id=row["employee_id"].strip(),
            start_date=row["start_date"].strip(),
            end_date=row["end_date"].strip(),
            source="csv",
        )
    except ValidationError as exc:
        reason = exc.errors()[0]["msg"].removeprefix("Value error, ")
        raise ValueError(f"Linha {number} do CSV de férias inválida: {reason}") from exc


def _delimiter(path: Path) -> str:
    """Aceita CSV separado por vírgula ou ponto e vírgula (padrão do Excel em português)."""
    first_line = path.read_text(encoding="utf-8-sig").splitlines()[0] if path.stat().st_size else ""
    return ";" if first_line.count(";") > first_line.count(",") else ","
