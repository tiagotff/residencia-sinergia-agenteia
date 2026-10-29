"""Estado de um caso trafegando pelo grafo do LangGraph.

O estado guarda apenas tipos serializáveis em JSON, para que o checkpointer possa
pausar e retomar o caso. Cada agente acrescenta suas próprias chaves.
"""

from typing import Any, TypedDict


class CaseState(TypedDict, total=False):
    """Estado do caso compartilhado pelos agentes."""

    session_id: str
    submission: dict[str, Any]
    resubmissions: int
    file_report: dict[str, Any]
    detected_type: str
    assessment: dict[str, Any]
    status: str
    protocol: str | None
    message: str
    missing: list[str]
