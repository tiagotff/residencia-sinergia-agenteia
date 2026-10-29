"""Ciclo agendado do Agente 3, seguido do Agente 4 para os alertas novos."""

import uuid
from datetime import date
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from sinergia.core.clock import Clock
from sinergia.core.sessions import thread_config
from sinergia.data.tasks import TaskRepository, TaskStatus


class MonitoringService:
    """Roda monitoramento e escalonamento sobre a base inteira, numa data de referência."""

    def __init__(self, graph: CompiledStateGraph, tasks: TaskRepository, clock: Clock) -> None:
        self._graph = graph
        self._tasks = tasks
        self._clock = clock

    def run(self, reference_date: date | None = None) -> dict[str, Any]:
        """Aplica A01–A05 e propõe encaminhamentos; devolve o resumo da execução.

        Cada execução é uma thread própria: os encaminhamentos propostos esperam a
        confirmação humana nela (``sinergia escalation list``).
        """
        day = reference_date or self._clock().date()
        session_id = f"ciclo-{day.isoformat()}-{uuid.uuid4().hex[:6]}"
        initial: dict[str, Any] = {"session_id": session_id}
        if reference_date:
            initial["monitoring_date"] = reference_date.isoformat()
        output = self._graph.invoke(initial, thread_config(session_id))
        proposals = len(self._tasks.for_session(session_id, TaskStatus.PROPOSED))
        return {**output["monitoring"], "session_id": session_id, "proposals": proposals}
