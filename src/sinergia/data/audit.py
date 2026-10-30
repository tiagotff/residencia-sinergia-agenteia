"""Trilha de auditoria: toda decisão registra regra, versão das regras e responsável.

Os detalhes nunca devem conter conteúdo do documento nem dados de saúde.
"""

import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from sinergia.core.clock import Clock
from sinergia.data.database import Database


class AuditEntry(BaseModel):
    """Linha da trilha de auditoria."""

    occurred_at: str
    actor: str
    action: str
    reference: str
    rule_ids: list[str]
    rules_version: str
    details: dict[str, Any]


class AuditLog:
    """Grava e consulta a trilha de auditoria."""

    def __init__(self, database: Database, clock: Clock, rules_version: str) -> None:
        self._db = database
        self._clock = clock
        self._rules_version = rules_version

    def record(
        self,
        actor: str,
        action: str,
        reference: str,
        rule_ids: Sequence[str] = (),
        details: dict[str, Any] | None = None,
    ) -> None:
        """Registra uma ação de um agente ou de uma pessoa."""
        with self._db.connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (occurred_at, actor, action, reference, rule_ids,"
                " rules_version, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._clock().isoformat(),
                    actor,
                    action,
                    reference,
                    json.dumps(list(rule_ids)),
                    self._rules_version,
                    json.dumps(details or {}, ensure_ascii=False),
                ),
            )

    def recent(self, limit: int = 200, actor: str | None = None) -> list[AuditEntry]:
        """Entradas mais recentes primeiro, opcionalmente de um ator."""
        sql, params = "SELECT * FROM audit_log", ()
        if actor:
            sql, params = sql + " WHERE actor = ?", (actor,)
        with self._db.connect() as conn:
            rows = conn.execute(f"{sql} ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
        return [_to_entry(row) for row in rows]

    def list_for(self, reference: str) -> list[AuditEntry]:
        """Lista as entradas de uma sessão ou protocolo, em ordem cronológica."""
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE reference = ? ORDER BY id", (reference,)
            ).fetchall()
        return [_to_entry(row) for row in rows]


def _to_entry(row: Any) -> AuditEntry:
    """Converte uma linha do banco em ``AuditEntry``."""
    data = dict(row)
    data["rule_ids"] = json.loads(data["rule_ids"])
    data["details"] = json.loads(data["details"])
    return AuditEntry.model_validate(data)
