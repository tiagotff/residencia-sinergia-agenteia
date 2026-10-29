"""Revisão humana do Agente 2: o que o profissional vê, como as correções entram e o serviço.

O CID nunca aparece na fila de revisão: ela mostra só se há CID no documento. O acesso
ao código fica restrito ao médico do trabalho, por requisição de detalhe (fase futura).
"""

from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from sinergia.agents.processing.extraction import derive_period
from sinergia.agents.processing.models import ExtractedFields, Extraction, ReviewDecision
from sinergia.core.domain import EXTRACTED_FIELDS
from sinergia.core.errors import SessionStateError
from sinergia.core.sessions import thread_config, waiting_payload
from sinergia.core.state import CaseState
from sinergia.data.absences import Absence, AbsenceRepository

_PERIOD_FIELDS = {"start_date", "end_date", "days"}
_TRUE = {"true", "sim", "s", "1", "yes"}
_FALSE = {"false", "nao", "não", "n", "0", "no"}


def review_payload(state: CaseState) -> dict[str, Any]:
    """Dados do caso para o revisor (sem o código CID)."""
    extraction = Extraction.model_validate(state["extraction"])
    fields = extraction.fields.model_dump(mode="json", exclude={"cid"})
    return {
        "kind": "review",
        "protocol": state["protocol"],
        "status": state.get("processing_status"),
        "violations": state["validation"]["violations"],
        "fields": fields,
        "cid_present": extraction.fields.cid is not None,
        "confidence": extraction.confidence,
        "derived": extraction.derived,
        "crm_check": state["crm_check"],
    }


def apply_corrections(extraction: Extraction, corrections: dict[str, Any]) -> Extraction:
    """Aplica as correções do revisor; a aprovação confirma todos os campos."""
    values = extraction.fields.model_dump()
    values.update({name: _coerce(name, value) for name, value in corrections.items()})
    stale = [name for name in extraction.derived if name not in corrections]
    if _PERIOD_FIELDS & set(corrections):
        values.update(dict.fromkeys(stale))
    try:
        fields = ExtractedFields.model_validate(values)
    except ValidationError as exc:
        raise ValueError(f"Correção inválida: {exc.errors()[0]['msg']}") from exc
    fields, derived = derive_period(fields)
    confidence = {**extraction.confidence, **dict.fromkeys(corrections, 1.0)}
    return extraction.model_copy(
        update={
            "fields": fields,
            "derived": derived if _PERIOD_FIELDS & set(corrections) else extraction.derived,
            "confidence": confidence,
            "human_verified": list(EXTRACTED_FIELDS),
        }
    )


def _coerce(name: str, value: Any) -> Any:
    """Converte textos digitados pelo revisor (ex.: 'sim' em 'signed')."""
    if name != "signed" or isinstance(value, bool) or value is None:
        return value
    text = str(value).strip().lower()
    if text in _TRUE | _FALSE:
        return text in _TRUE
    raise ValueError("Correção inválida: 'signed' aceita sim/não.")


class ReviewCase(BaseModel):
    """Caso na fila de revisão."""

    protocol: str
    status: str
    payload: dict[str, Any]


class ReviewService:
    """Fila de revisão humana sobre o grafo do caso."""

    def __init__(self, graph: CompiledStateGraph, absences: AbsenceRepository) -> None:
        self._graph = graph
        self._absences = absences

    def pending(self) -> list[ReviewCase]:
        """Casos aguardando decisão, do mais antigo para o mais novo."""
        cases = (self._case(absence) for absence in self._absences.open_reviews())
        return [case for case in cases if case is not None]

    def get(self, protocol: str) -> ReviewCase:
        """Um caso da fila."""
        case = self._case(self._absences.get(protocol))
        if case is None:
            raise SessionStateError(f"O protocolo {protocol} não está aguardando revisão.")
        return case

    def decide(self, protocol: str, decision: ReviewDecision) -> Absence:
        """Retoma o caso com a decisão do profissional e devolve o registro atualizado."""
        absence = self._absences.get(protocol)
        if self._case(absence) is None:
            raise SessionStateError(f"O protocolo {protocol} não está aguardando revisão.")
        apply_corrections(_as_extraction(absence), decision.corrections)  # valida antes de retomar
        self._graph.invoke(
            Command(resume=decision.model_dump(mode="json")), thread_config(absence.session_id)
        )
        return self._absences.get(protocol)

    def _case(self, absence: Absence) -> ReviewCase | None:
        """Monta o caso a partir da pausa do grafo, se ela for de revisão."""
        payload = waiting_payload(self._graph, absence.session_id, "review")
        if payload is None:
            return None
        return ReviewCase(protocol=absence.protocol, status=absence.status.value, payload=payload)


def _as_extraction(absence: Absence) -> Extraction:
    """Reconstrói a extração a partir do registro salvo, para validar correções."""
    fields = ExtractedFields.model_validate(absence.model_dump(include=set(EXTRACTED_FIELDS)))
    return Extraction(
        employee_id=absence.employee_id,
        document_type=absence.document_type,
        fields=fields,
        confidence=absence.field_confidence,
        method=absence.extraction_method,
    )
