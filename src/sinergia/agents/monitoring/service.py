"""Execução do Agente 3 fora do grafo do caso: o ciclo agendado sobre a base inteira."""

from datetime import date
from typing import Any

from langgraph.graph.state import CompiledStateGraph


class MonitoringService:
    """Roda o subgrafo de monitoramento para uma data de referência."""

    def __init__(self, graph: CompiledStateGraph) -> None:
        self._graph = graph

    def run(self, reference_date: date | None = None) -> dict[str, Any]:
        """Executa as regras A01–A05 e devolve o resumo (alertas novos, suprimidos)."""
        initial = {"monitoring_date": reference_date.isoformat()} if reference_date else {}
        return self._graph.invoke(initial)["monitoring"]
