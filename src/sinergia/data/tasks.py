"""Encaminhamentos do Agente 4: cada um é uma tarefa para uma área, com urgência e prazo.

Ciclo de vida:
    proposto → (confirmação humana) → aberto → concluido
                                    ↘ cancelado     ↘ reescalado (vencido, com nova tarefa)
                                                    ↘ vencido (sem resposta e sem novo destino)
"""

import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from sinergia.core.errors import NotFoundError
from sinergia.data.database import Database

_JSON_COLUMNS = ("breakdown",)


class TaskStatus(StrEnum):
    """Situação de um encaminhamento."""

    PROPOSED = "proposto"
    OPEN = "aberto"
    DONE = "concluido"
    CANCELLED = "cancelado"
    REESCALATED = "reescalado"
    EXPIRED = "vencido"


class Task(BaseModel):
    """Encaminhamento de uma demanda para um destino."""

    demand_key: str
    session_id: str
    origin: str
    rule_id: str
    title: str
    destination: str
    urgency: str
    detail: str
    subject: str
    summary: str
    utility: float
    breakdown: dict[str, Any] = Field(default_factory=dict)
    primary_choice: bool = False
    deadline: date | None = None
    due_date: date | None = None
    status: TaskStatus = TaskStatus.PROPOSED
    attempt: int = 0
    parent_id: int | None = None
    decided_by: str | None = None
    note: str | None = None
    rules_version: str


class StoredTask(Task):
    """Encaminhamento gravado."""

    id: int
    created_at: datetime
    updated_at: datetime


class TaskRepository:
    """Persistência dos encaminhamentos."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, task: Task, at: datetime) -> int | None:
        """Grava a tarefa; devolve o id, ou None se ela já existia."""
        data = task.model_dump(mode="json")
        data["breakdown"] = json.dumps(data["breakdown"], ensure_ascii=False)
        data |= {"created_at": at.isoformat(), "updated_at": at.isoformat()}
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self._db.connect() as conn:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO tasks ({columns}) VALUES ({marks})", tuple(data.values())
            )
        return cursor.lastrowid if cursor.rowcount == 1 else None

    def get(self, task_id: int) -> StoredTask:
        """Uma tarefa pelo id."""
        found = self._select("WHERE id = ?", (task_id,))
        if not found:
            raise NotFoundError(f"Encaminhamento não encontrado: {task_id}")
        return found[0]

    def find_step(self, demand_key: str, destination: str, attempt: int) -> StoredTask | None:
        """A tarefa de uma demanda num destino e numa tentativa, se existir."""
        found = self._select(
            "WHERE demand_key = ? AND destination = ? AND attempt = ?",
            (demand_key, destination, attempt),
        )
        return found[0] if found else None

    def known_demand(self, demand_key: str) -> bool:
        """Se a demanda já foi encaminhada (em qualquer situação)."""
        return bool(self._select("WHERE demand_key = ?", (demand_key,)))

    def for_session(self, session_id: str, status: TaskStatus | None = None) -> list[StoredTask]:
        """Tarefas de uma sessão (caso ou ciclo de monitoramento)."""
        if status is None:
            return self._select("WHERE session_id = ?", (session_id,))
        return self._select("WHERE session_id = ? AND status = ?", (session_id, status.value))

    def find(
        self, status: TaskStatus | None = None, destination: str | None = None
    ) -> list[StoredTask]:
        """Tarefas filtradas por situação e destino."""
        clauses, params = [], []
        for column, value in (("status", status), ("destination", destination)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(str(value))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return self._select(where, tuple(params))

    def proposed_sessions(self) -> list[tuple[str, str]]:
        """Sessões com propostas aguardando confirmação: (sessão, origem), mais antigas antes."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT session_id, origin, MIN(id) AS first FROM tasks WHERE status = ?"
                " GROUP BY session_id, origin ORDER BY first",
                (TaskStatus.PROPOSED.value,),
            ).fetchall()
        return [(row["session_id"], row["origin"]) for row in rows]

    def overdue(self, today: date) -> list[StoredTask]:
        """Tarefas abertas com prazo vencido."""
        return self._select(
            "WHERE status = ? AND due_date < ?", (TaskStatus.OPEN.value, today.isoformat())
        )

    def update(self, task_id: int, at: datetime, **changes: Any) -> None:
        """Atualiza campos da tarefa (situação, prazo, destino, quem decidiu)."""
        values = {k: (v.value if isinstance(v, StrEnum) else v) for k, v in changes.items()}
        values = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in values.items()}
        values["updated_at"] = at.isoformat()
        sets = ", ".join(f"{column} = ?" for column in values)
        with self._db.connect() as conn:
            conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", (*values.values(), task_id))

    def _select(self, where: str, params: tuple) -> list[StoredTask]:
        """Consulta genérica, na ordem de criação."""
        with self._db.connect() as conn:
            rows = conn.execute(f"SELECT * FROM tasks {where} ORDER BY id", params).fetchall()
        return [_from_row(dict(row)) for row in rows]


def _from_row(row: dict[str, Any]) -> StoredTask:
    """Converte uma linha do banco em ``StoredTask``."""
    for column in _JSON_COLUMNS:
        row[column] = json.loads(row[column])
    return StoredTask.model_validate(row)
