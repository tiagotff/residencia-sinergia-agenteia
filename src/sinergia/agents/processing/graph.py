"""Subgrafo LangGraph do Agente 2 (reativo simples).

    read_document → verify_crm → validate ─┬─ válido ──→ register_valid → check_deadlines → FIM
                                            └─ violou ──→ register_for_review → await_review
                                                                                    │
                       validate ←── apply_review (aprovar, com correções) ←─────────┤
                       FIM      ←── apply_review (invalidar) ←────────────────────────┘

A pausa em ``await_review`` usa ``interrupt``: o caso espera o profissional decidir.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from sinergia.agents.processing.crm import CrmVerifier
from sinergia.agents.processing.deadlines import legal_escalations
from sinergia.agents.processing.extraction import FieldExtractor, build_extraction
from sinergia.agents.processing.models import (
    CrmCheck,
    CrmStatus,
    Extraction,
    ReviewDecision,
    Validation,
)
from sinergia.agents.processing.review import apply_corrections, review_payload
from sinergia.agents.processing.text_reader import DocumentTextReader
from sinergia.agents.processing.validation import validate_absence
from sinergia.core.clock import Clock
from sinergia.core.domain import AbsenceStatus
from sinergia.core.rules import RuleCatalog
from sinergia.core.state import CaseState
from sinergia.data.absences import Absence, AbsenceRepository
from sinergia.data.audit import AuditLog
from sinergia.data.intakes import IntakeRepository
from sinergia.data.vacations import VacationRepository

ACTOR = "agente_2_processamento"


@dataclass(frozen=True)
class ProcessingDeps:
    """Dependências injetadas no Agente 2."""

    rules: RuleCatalog
    reader: DocumentTextReader
    extractor: FieldExtractor
    crm: CrmVerifier
    intakes: IntakeRepository
    absences: AbsenceRepository
    vacations: VacationRepository
    audit: AuditLog
    clock: Clock


class ProcessingNodes:
    """Nós do subgrafo; cada um faz uma etapa do ciclo do agente."""

    def __init__(self, deps: ProcessingDeps) -> None:
        self._deps = deps

    def read_document(self, state: CaseState) -> dict[str, Any]:
        """Percepção: lê o texto e extrai os campos. O texto não vai para o estado."""
        intake = self._deps.intakes.get(state["protocol"])
        read = self._deps.reader.read(Path(intake.file_path or ""), intake.mime_type)
        extraction = build_extraction(
            self._deps.extractor,
            read.text,
            intake.employee_id,
            intake.document_type,
            read.ocr_confidence,
        )
        rules = ["R09"] if extraction.cid_discarded else []
        self._deps.audit.record(
            ACTOR,
            "extracao",
            intake.protocol,
            rules,
            {"metodo": extraction.method, "fonte_texto": read.source},
        )
        return {"extraction": extraction.model_dump(mode="json"), "review": {}}

    def verify_crm(self, state: CaseState) -> dict[str, Any]:
        """Percepção: consulta a situação do CRM (R06)."""
        fields = Extraction.model_validate(state["extraction"]).fields
        if not (fields.crm_number and fields.crm_uf):
            check = CrmCheck(
                status=CrmStatus.NOT_VERIFIED, detail="CRM ausente no documento.", source="nenhuma"
            )
        else:
            check = self._deps.crm.verify(fields.crm_number, fields.crm_uf)
        return {"crm_check": check.model_dump(mode="json")}

    def validate(self, state: CaseState) -> dict[str, Any]:
        """Decisão: aplica R04–R08 com regras fixas."""
        extraction = Extraction.model_validate(state["extraction"])
        validation = validate_absence(
            extraction,
            CrmCheck.model_validate(state["crm_check"]),
            self._deps.absences.for_employee(extraction.employee_id or "", state["protocol"]),
            self._deps.rules.processing,
            human_approved=state.get("review", {}).get("decision") == "aprovar",
            vacations=self._deps.vacations.for_employee(extraction.employee_id or ""),
        )
        self._deps.audit.record(ACTOR, "validacao", state["protocol"], validation.rule_ids)
        return {"validation": validation.model_dump(mode="json")}

    def route_validation(
        self, state: CaseState
    ) -> Literal["register_valid", "register_for_review"]:
        """Registro válido segue; qualquer violação vai para revisão humana."""
        valid = Validation.model_validate(state["validation"]).valid
        return "register_valid" if valid else "register_for_review"

    def register_for_review(self, state: CaseState) -> dict[str, Any]:
        """Ação: grava o registro como pendente ou em revisão."""
        validation = Validation.model_validate(state["validation"])
        absence = self._save(state, validation.status, validation.rule_ids)
        self._deps.audit.record(
            ACTOR, "enviado_para_revisao", absence.protocol, validation.rule_ids
        )
        return {"processing_status": absence.status.value}

    def await_review(self, state: CaseState) -> dict[str, Any]:
        """Pausa até um profissional aprovar (com correções) ou invalidar."""
        decision = interrupt(review_payload(state))
        return {"review": ReviewDecision.model_validate(decision).model_dump(mode="json")}

    def apply_review(self, state: CaseState) -> dict[str, Any]:
        """Aplica a decisão humana; correções viram exemplo para melhorar a extração."""
        decision = ReviewDecision.model_validate(state["review"])
        self._deps.audit.record(
            decision.reviewer,
            f"revisao_{decision.decision}",
            state["protocol"],
            details={"nota": decision.note},
        )
        if decision.decision == "invalidar":
            self._save(state, AbsenceStatus.INVALIDATED, [])
            return {"processing_status": AbsenceStatus.INVALIDATED.value}
        extraction = Extraction.model_validate(state["extraction"])
        corrected = apply_corrections(extraction, decision.corrections)
        self._store_feedback(state["protocol"], extraction, corrected, decision)
        return {"extraction": corrected.model_dump(mode="json")}

    def route_review(self, state: CaseState) -> Literal["validate", "__end__"]:
        """Invalidado encerra; aprovado volta para a validação com as correções."""
        invalidated = state.get("processing_status") == AbsenceStatus.INVALIDATED.value
        return END if invalidated else "validate"

    def register_valid(self, state: CaseState) -> dict[str, Any]:
        """Ação: grava o registro válido na tabela de afastamentos."""
        absence = self._save(state, AbsenceStatus.VALID, [])
        self._deps.audit.record(ACTOR, "afastamento_registrado", absence.protocol)
        return {"processing_status": absence.status.value}

    def check_deadlines(self, state: CaseState) -> dict[str, Any]:
        """R10/R11: pendências com prazo legal seguem direto para o escalonamento."""
        absence = self._deps.absences.get(state["protocol"])
        others = self._deps.absences.for_employee(absence.employee_id or "", absence.protocol)
        escalations = legal_escalations(absence, others, self._deps.rules.processing)
        for item in escalations:
            self._deps.intakes.open_pendency(
                absence.protocol, item.kind, item.target_area, item.rule_id, self._deps.clock()
            )
            self._deps.audit.record(
                ACTOR,
                "escalonamento_legal",
                absence.protocol,
                [item.rule_id],
                {"area": item.target_area},
            )
        return {"escalations": [item.model_dump(mode="json") for item in escalations]}

    def _save(self, state: CaseState, status: AbsenceStatus, rule_ids: list[str]) -> Absence:
        """Grava o afastamento com os campos atuais e a última decisão humana."""
        extraction = Extraction.model_validate(state["extraction"])
        absence = Absence(
            protocol=state["protocol"],
            session_id=state["session_id"],
            employee_id=extraction.employee_id,
            document_type=extraction.document_type,
            crm_status=CrmCheck.model_validate(state["crm_check"]).status.value,
            status=status,
            violated_rules=rule_ids,
            field_confidence=extraction.confidence,
            extraction_method=extraction.method,
            rules_version=self._deps.rules.version,
            updated_at=self._deps.clock(),
            **_review_fields(state),
            **extraction.fields.model_dump(),
        )
        self._deps.absences.save(absence)
        return absence

    def _store_feedback(
        self, protocol: str, before: Extraction, after: Extraction, decision: ReviewDecision
    ) -> None:
        """Registra cada campo corrigido (valor extraído → valor do revisor)."""
        old, new = before.fields.model_dump(), after.fields.model_dump()
        for name in decision.corrections:
            if old[name] != new[name]:
                self._deps.absences.add_feedback(
                    protocol, name, old[name], new[name], decision.reviewer, self._deps.clock()
                )


def _review_fields(state: CaseState) -> dict[str, Any]:
    """Quem revisou, a decisão e a nota (vazios antes de qualquer revisão)."""
    review = state.get("review") or {}
    return {
        "reviewed_by": review.get("reviewer"),
        "review_decision": review.get("decision"),
        "review_note": review.get("note"),
    }


def build_processing_graph(
    deps: ProcessingDeps, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Monta e compila o subgrafo do Agente 2."""
    nodes = ProcessingNodes(deps)
    graph = StateGraph(CaseState)
    steps: dict[str, Callable[[CaseState], dict[str, Any]]] = {
        "read_document": nodes.read_document,
        "verify_crm": nodes.verify_crm,
        "validate": nodes.validate,
        "register_for_review": nodes.register_for_review,
        "await_review": nodes.await_review,
        "apply_review": nodes.apply_review,
        "register_valid": nodes.register_valid,
        "check_deadlines": nodes.check_deadlines,
    }
    for name, step in steps.items():
        graph.add_node(name, step)
    _wire(graph, nodes)
    return graph.compile(checkpointer=checkpointer)


def _wire(graph: StateGraph, nodes: ProcessingNodes) -> None:
    """Liga os nós conforme o fluxo do agente."""
    graph.add_edge(START, "read_document")
    graph.add_edge("read_document", "verify_crm")
    graph.add_edge("verify_crm", "validate")
    graph.add_conditional_edges("validate", nodes.route_validation)
    graph.add_edge("register_for_review", "await_review")
    graph.add_edge("await_review", "apply_review")
    graph.add_conditional_edges("apply_review", nodes.route_review)
    graph.add_edge("register_valid", "check_deadlines")
    graph.add_edge("check_deadlines", END)
