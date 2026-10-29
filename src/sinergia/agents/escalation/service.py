"""Fachada do Agente 4: fila de confirmação, conclusão das tarefas e reescalonamento."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel

from sinergia.agents.escalation.graph import ACTOR, check_decision
from sinergia.agents.escalation.models import EscalationDecision
from sinergia.core.clock import Clock
from sinergia.core.errors import SessionStateError
from sinergia.core.rules import EscalationRules
from sinergia.core.sessions import thread_config, waiting_payload
from sinergia.data.audit import AuditLog
from sinergia.data.tasks import StoredTask, Task, TaskRepository, TaskStatus


class PendingConfirmation(BaseModel):
    """Encaminhamentos de uma sessão aguardando confirmação humana."""

    session_id: str
    origin: str
    payload: dict[str, Any]


@dataclass
class SweepResult:
    """O que o acompanhamento de prazos fez."""

    reescalated: list[int] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)


class EscalationService:
    """Confirmação humana (retomando o grafo certo) e acompanhamento dos prazos."""

    def __init__(
        self,
        graphs: dict[str, CompiledStateGraph],
        tasks: TaskRepository,
        rules: EscalationRules,
        audit: AuditLog,
        clock: Clock,
    ) -> None:
        self._graphs = graphs
        self._tasks = tasks
        self._rules = rules
        self._audit = audit
        self._clock = clock

    def pending(self) -> list[PendingConfirmation]:
        """Sessões com encaminhamentos propostos, das mais antigas para as mais novas."""
        found = (self._pending(s, o) for s, o in self._tasks.proposed_sessions())
        return [item for item in found if item is not None]

    def get(self, session_id: str) -> PendingConfirmation:
        """Uma confirmação pendente."""
        for item in self.pending():
            if item.session_id == session_id:
                return item
        raise SessionStateError(f"A sessão {session_id} não tem encaminhamentos a confirmar.")

    def decide(self, session_id: str, decision: EscalationDecision) -> list[StoredTask]:
        """Retoma o grafo com a decisão e devolve as tarefas da sessão."""
        pending = self.get(session_id)
        check_decision(
            decision, self._tasks.for_session(session_id, TaskStatus.PROPOSED), self._rules
        )
        command = Command(resume=decision.model_dump(mode="json"))
        self._graphs[pending.origin].invoke(command, thread_config(session_id))
        return self._tasks.for_session(session_id)

    def complete(self, task_id: int, by: str, note: str | None = None) -> StoredTask:
        """A área informa que resolveu a tarefa."""
        task = self._tasks.get(task_id)
        if task.status is not TaskStatus.OPEN:
            raise SessionStateError(f"O encaminhamento {task_id} não está aberto.")
        self._tasks.update(task_id, self._clock(), status=TaskStatus.DONE, decided_by=by, note=note)
        self._audit.record(
            by,
            "encaminhamento_concluido",
            task.session_id,
            [task.rule_id],
            {"tarefa": task_id, "destino": task.destination},
        )
        return self._tasks.get(task_id)

    def sweep(self) -> SweepResult:
        """Reescala as tarefas vencidas sem resposta (urgência +1, próximo da cadeia)."""
        now, result = self._clock(), SweepResult()
        for task in self._tasks.overdue(now.date()):
            if task.attempt >= self._rules.max_reescalations:
                self._expire(task, now)
                result.expired.append(task.id)
            else:
                result.reescalated.append(self._reescalate(task, now))
        result.reescalated = sorted(set(result.reescalated))
        return result

    def _pending(self, session_id: str, origin: str) -> PendingConfirmation | None:
        """Monta a confirmação a partir da pausa do grafo."""
        payload = waiting_payload(self._graphs[origin], session_id, "escalation")
        if payload is None:
            return None
        return PendingConfirmation(session_id=session_id, origin=origin, payload=payload)

    def _reescalate(self, task: StoredTask, now: datetime) -> int:
        """Abre a tarefa seguinte da cadeia (ou junta-se a ela) e encerra a vencida."""
        child = self._next_step(task, now)
        existing = self._tasks.find_step(task.demand_key, child.destination, child.attempt)
        child_id = existing.id if existing else self._tasks.add(child, now) or 0
        self._tasks.update(task.id, now, status=TaskStatus.REESCALATED)
        self._audit.record(
            ACTOR,
            "encaminhamento_reescalado",
            task.session_id,
            [task.rule_id],
            {
                "tarefa": task.id,
                "nova_tarefa": child_id,
                "destino": child.destination,
                "urgencia": child.urgency,
            },
        )
        return child_id

    def _next_step(self, task: StoredTask, now: datetime) -> Task:
        """Próximo destino da cadeia, um nível de urgência acima, já aberto."""
        urgency = _raise(task.urgency, list(self._rules.urgencies))
        sla = self._rules.urgencies[urgency].sla_days
        data = task.model_dump(exclude={"id", "created_at", "updated_at"})
        data |= {
            "destination": self._rules.chain[task.destination],
            "urgency": urgency,
            "status": TaskStatus.OPEN,
            "attempt": task.attempt + 1,
            "parent_id": task.id,
            "due_date": now.date() + timedelta(days=sla),
            "decided_by": ACTOR,
            "note": f"Reescalonado: o encaminhamento #{task.id} venceu sem resposta.",
        }
        return Task.model_validate(data)

    def _expire(self, task: StoredTask, now: datetime) -> None:
        """Esgotadas as tentativas: fica registrado como vencido, sem novo destino."""
        self._tasks.update(task.id, now, status=TaskStatus.EXPIRED)
        self._audit.record(
            ACTOR,
            "encaminhamento_vencido",
            task.session_id,
            [task.rule_id],
            {"tarefa": task.id, "destino": task.destination},
        )


def _raise(urgency: str, levels: list[str]) -> str:
    """Um nível acima (a urgência máxima continua máxima)."""
    return levels[min(levels.index(urgency) + 1, len(levels) - 1)]
