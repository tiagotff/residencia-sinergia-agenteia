"""Leitura das pausas (interrupt) de um caso no grafo do LangGraph.

Cada pausa leva um ``kind``: "employee" quando o caso espera o colaborador (Agente 1)
e "review" quando espera o revisor humano (Agente 2).
"""

from typing import Any

from langgraph.graph.state import CompiledStateGraph

from sinergia.core.errors import NotFoundError


def thread_config(session_id: str) -> dict[str, Any]:
    """Configuração de thread do LangGraph para a sessão do caso."""
    return {"configurable": {"thread_id": session_id}}


def waiting_payload(graph: CompiledStateGraph, session_id: str, kind: str) -> dict[str, Any] | None:
    """Conteúdo da pausa pendente da sessão, se for do tipo pedido."""
    snapshot = graph.get_state(thread_config(session_id), subgraphs=True)
    if not snapshot.values:
        raise NotFoundError(f"Sessão não encontrada: {session_id}")
    for task in snapshot.tasks:
        for item in _interrupts(task):
            if isinstance(item.value, dict) and item.value.get("kind") == kind:
                return item.value
    return None


def _interrupts(task: Any) -> list[Any]:
    """Pausas da tarefa, inclusive as de subgrafos."""
    nested = task.state.tasks if task.state is not None and hasattr(task.state, "tasks") else ()
    return [*task.interrupts, *(item for sub in nested for item in sub.interrupts)]
