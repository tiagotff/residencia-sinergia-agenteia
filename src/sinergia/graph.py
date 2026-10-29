"""Grafo do caso: liga os agentes em cadeia, cada um como subgrafo.

    START → reception (A1) ─┬─ recebido ──→ processing (A2) → FIM
                            └─ pendente RH → FIM

Um caso é uma thread do LangGraph: as pausas do colaborador (A1) e do revisor (A2)
ficam no mesmo checkpoint e são retomadas pelo identificador da sessão.
"""

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from sinergia.core.domain import CaseStatus
from sinergia.core.state import CaseState


def _after_reception(state: CaseState) -> Literal["processing", "__end__"]:
    """Só documentos recebidos seguem para o processamento."""
    return "processing" if state.get("status") == CaseStatus.RECEIVED.value else END


def build_case_graph(
    reception: CompiledStateGraph,
    processing: CompiledStateGraph,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """Compõe os subgrafos dos agentes num único grafo com checkpoint."""
    graph = StateGraph(CaseState)
    graph.add_node("reception", reception)
    graph.add_node("processing", processing)
    graph.add_edge(START, "reception")
    graph.add_conditional_edges("reception", _after_reception)
    graph.add_edge("processing", END)
    return graph.compile(checkpointer=checkpointer)
