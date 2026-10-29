"""Fachada do Agente 1: inicia e retoma sessões de envio sobre o subgrafo."""

import uuid
from datetime import date
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel

from sinergia.agents.reception.models import Submission
from sinergia.core.domain import CaseStatus, DocumentType
from sinergia.core.errors import NotFoundError, SessionStateError
from sinergia.data.file_store import FileStore


class ReceptionInput(BaseModel):
    """Envio ou resposta do colaborador, vindo da API ou da CLI."""

    employee_id: str | None = None
    channel: str = "portal"
    declared_type: DocumentType | None = None
    absence_start: date | None = None
    file_name: str | None = None
    content: bytes | None = None


class ReceptionResult(BaseModel):
    """Resposta ao colaborador após cada interação."""

    session_id: str
    status: CaseStatus
    message: str
    missing: list[str]
    protocol: str | None = None


class ReceptionService:
    """Conduz a conversa de recepção; cada sessão é uma thread do LangGraph."""

    def __init__(self, graph: CompiledStateGraph, files: FileStore) -> None:
        self._graph = graph
        self._files = files

    def start(self, data: ReceptionInput) -> ReceptionResult:
        """Recebe o primeiro envio e roda o agente até concluir ou pausar."""
        session_id = uuid.uuid4().hex
        initial = {
            "session_id": session_id,
            "submission": self._to_submission(data),
            "resubmissions": 0,
        }
        output = self._graph.invoke(initial, _config(session_id))
        return _to_result(session_id, output)

    def reply(self, session_id: str, data: ReceptionInput) -> ReceptionResult:
        """Retoma uma sessão pausada com a resposta do colaborador."""
        self._ensure_waiting(session_id)
        command = Command(resume=self._to_submission(data))
        output = self._graph.invoke(command, _config(session_id))
        return _to_result(session_id, output)

    def _ensure_waiting(self, session_id: str) -> None:
        """Só aceita resposta em sessões existentes e pausadas."""
        snapshot = self._graph.get_state(_config(session_id))
        if not snapshot.values:
            raise NotFoundError(f"Sessão não encontrada: {session_id}")
        if not snapshot.interrupts:
            raise SessionStateError(f"A sessão {session_id} não está aguardando resposta.")

    def _to_submission(self, data: ReceptionInput) -> dict[str, Any]:
        """Grava o arquivo na área temporária e monta o envio serializável."""
        submission = Submission(
            employee_id=data.employee_id,
            channel=data.channel,
            declared_type=data.declared_type,
            absence_start=data.absence_start,
        )
        if data.content is not None:
            name = data.file_name or "documento"
            path = self._files.stage(data.content, name)
            submission = submission.model_copy(
                update={"file_path": str(path), "original_name": name}
            )
        return submission.model_dump(mode="json")


def _config(session_id: str) -> dict[str, Any]:
    """Configuração de thread do LangGraph para a sessão."""
    return {"configurable": {"thread_id": session_id}}


def _to_result(session_id: str, output: dict[str, Any]) -> ReceptionResult:
    """Converte a saída do grafo (concluída ou pausada) em resposta."""
    if "__interrupt__" in output:
        payload = output["__interrupt__"][0].value
        return ReceptionResult(
            session_id=session_id,
            status=CaseStatus.AWAITING_EMPLOYEE,
            message=payload["message"],
            missing=payload["missing"],
        )
    return ReceptionResult(
        session_id=session_id,
        status=CaseStatus(output["status"]),
        message=output["message"],
        missing=output.get("missing", []),
        protocol=output.get("protocol"),
    )
