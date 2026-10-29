"""Grafo do caso: liga os agentes em cadeia, cada um como subgrafo.

    START → reception (A1) ─┬─ recebido ──→ processing (A2) ─┬─ válido ──→ monitoring (A3) → FIM
                            └─ pendente RH → FIM             └─ invalidado → FIM

Um caso é uma thread do LangGraph: as pausas do colaborador (A1) e do revisor (A2)
ficam no mesmo checkpoint e são retomadas pelo identificador da sessão.
"""

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sinergia.core.domain import AbsenceStatus, CaseStatus
from sinergia.core.state import CaseState


def _after_reception(state: CaseState) -> Literal["processing", "__end__"]:
    """Só documentos recebidos seguem para o processamento."""
    return "processing" if state.get("status") == CaseStatus.RECEIVED.value else END


def _after_processing(state: CaseState) -> Literal["monitoring", "__end__"]:
    """Só afastamentos válidos alimentam o monitoramento."""
    valid = state.get("processing_status") == AbsenceStatus.VALID.value
    return "monitoring" if valid else END


def build_case_graph(
    agents: dict[str, CompiledStateGraph], checkpointer: BaseCheckpointSaver
) -> CompiledStateGraph:
    """Compõe os subgrafos dos agentes (reception, processing, monitoring) com checkpoint."""
    graph = StateGraph(CaseState)
    for name in ("reception", "processing", "monitoring"):
        graph.add_node(name, agents[name])
    graph.add_edge(START, "reception")
    graph.add_conditional_edges("reception", _after_reception)
    graph.add_conditional_edges("processing", _after_processing)
    graph.add_edge("monitoring", END)
    return graph.compile(checkpointer=checkpointer)
