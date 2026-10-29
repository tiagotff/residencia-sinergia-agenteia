"""Alertas do Agente 3: sempre sobre grupos (ou pseudônimos), com a evidência que os gerou."""

import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from sinergia.data.database import Database

_JSON_COLUMNS = ("details",)


class Alert(BaseModel):
    """Alerta explicável: regra, grupo, período, métrica comparada e limiar."""

    rule_id: str
    scope_type: str
    scope: str
    period_start: date
    period_end: date
    metric: str
    value: float
    reference: float | None = None
    threshold: float
    group_size: int
    sensitive: bool = False
    explanation: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    status: str = "aberto"

    @property
    def fingerprint(self) -> str:
        """Identidade do alerta: a mesma regra, grupo e período não geram outro alerta."""
        return f"{self.rule_id}|{self.scope_type}|{self.scope}|{self.period_start.isoformat()}"


class StoredAlert(Alert):
    """Alerta já gravado."""

    id: int
    rules_version: str
    created_at: datetime


class AlertRepository:
    """Persistência dos alertas, sem duplicar o mesmo achado."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def add(self, alert: Alert, rules_version: str, at: datetime) -> bool:
        """Grava o alerta; devolve False se ele já existia ou continua um alerta aberto."""
        if self.continues_open(alert):
            return False
        data = alert.model_dump(mode="json")
        data["details"] = json.dumps(data["details"], ensure_ascii=False)
        data |= {
            "fingerprint": alert.fingerprint,
            "rules_version": rules_version,
            "created_at": at.isoformat(),
        }
        columns = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        with self._db.connect() as conn:
            cursor = conn.execute(
                f"INSERT OR IGNORE INTO alerts ({columns}) VALUES ({marks})", tuple(data.values())
            )
        return cursor.rowcount == 1

    def continues_open(self, alert: Alert) -> bool:
        """Já há alerta aberto da mesma regra e grupo cujo período toca o deste.

        As janelas andam um dia por execução; sem isso, um pico que continua viraria um
        alerta novo por dia. Fechado o alerta anterior, o próximo volta a ser gerado.
        """
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM alerts WHERE status = 'aberto' AND rule_id = ? AND scope_type = ?"
                " AND scope = ? AND period_end >= ? AND period_start <= ?"
                " AND COALESCE(json_extract(details, '$.grupo_cid'), '') = ?",
                _continuation_key(alert),
            ).fetchone()
        return row is not None

    def list(self, status: str | None = None) -> list[StoredAlert]:
        """Alertas, do mais recente para o mais antigo."""
        sql = "SELECT * FROM alerts"
        params: tuple[Any, ...] = ()
        if status:
            sql, params = sql + " WHERE status = ?", (status,)
        with self._db.connect() as conn:
            rows = conn.execute(sql + " ORDER BY id DESC", params).fetchall()
        return [_from_row(dict(row)) for row in rows]


def _from_row(row: dict[str, Any]) -> StoredAlert:
    """Converte uma linha do banco em ``StoredAlert``."""
    row.pop("fingerprint", None)
    for column in _JSON_COLUMNS:
        row[column] = json.loads(row[column])
    return StoredAlert.model_validate(row)


def _continuation_key(alert: Alert) -> tuple[str, ...]:
    """Parâmetros da consulta de continuação."""
    return (
        alert.rule_id,
        alert.scope_type,
        alert.scope,
        alert.period_start.isoformat(),
        alert.period_end.isoformat(),
        str(alert.details.get("grupo_cid", "")),
    )
