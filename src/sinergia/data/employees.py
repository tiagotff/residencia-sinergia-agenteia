"""Cadastro mínimo de colaboradores para o Agente 3: setor, função, turno e função crítica.

Não guarda nome nem dado de saúde: só o necessário para comparar grupos. Vem do sistema
de RH; enquanto não há integração, entra por CSV exportado da folha.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator

from sinergia.data.database import Database

CSV_COLUMNS = ("employee_id", "sector", "role", "shift", "critical_role")
_TRUE = {"sim", "s", "true", "1", "yes", "x"}


class Employee(BaseModel):
    """Lotação de um colaborador."""

    employee_id: str
    sector: str
    role: str
    shift: str
    critical_role: bool = False
    active: bool = True

    @field_validator("critical_role", mode="before")
    @classmethod
    def _flag(cls, value: Any) -> Any:
        """Aceita sim/não, true/false e 1/0."""
        return str(value).strip().lower() in _TRUE if isinstance(value, str) else value


class EmployeeRepository:
    """Persistência e importação do cadastro."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def upsert(self, employee: Employee, at: datetime) -> None:
        """Insere ou atualiza a lotação do colaborador."""
        data = employee.model_dump()
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO employees (employee_id, sector, role, shift,"
                " critical_role, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*data.values(), at.isoformat()),
            )

    def active(self) -> list[Employee]:
        """Colaboradores ativos."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT employee_id, sector, role, shift, critical_role, active FROM employees"
                " WHERE active = 1 ORDER BY employee_id"
            ).fetchall()
        return [Employee.model_validate(dict(row)) for row in rows]

    def import_csv(self, path: Path, at: datetime) -> int:
        """Importa (ou atualiza) o cadastro a partir de CSV; devolve quantos entraram."""
        employees = read_employees_csv(path)
        for employee in employees:
            self.upsert(employee, at)
        return len(employees)


def read_employees_csv(path: Path) -> list[Employee]:
    """Lê e valida todas as linhas antes de gravar qualquer uma."""
    text = path.read_text(encoding="utf-8-sig")
    delimiter = ";" if text.split("\n", 1)[0].count(";") else ","
    reader = csv.DictReader(text.splitlines(), delimiter=delimiter)
    missing = set(CSV_COLUMNS) - set(reader.fieldnames or [])
    if missing:
        raise ValueError(f"Colunas ausentes no CSV de colaboradores: {sorted(missing)}")
    return [_row(number, row) for number, row in enumerate(reader, start=2)]


def _row(number: int, row: dict[str, str]) -> Employee:
    """Converte uma linha, indicando a linha em caso de erro."""
    try:
        return Employee.model_validate({key: row[key].strip() for key in CSV_COLUMNS})
    except (ValidationError, AttributeError) as exc:
        raise ValueError(f"Linha {number} do CSV de colaboradores inválida.") from exc
