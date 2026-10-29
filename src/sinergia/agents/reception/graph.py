"""Subgrafo LangGraph do Agente 1, no ciclo Percepção → Decisão → Ação.

perceive → decide ─┬─ completo ──────────────→ store_dossier → FIM
                   ├─ falta algo ────────────→ ask_employee → wait_for_employee ─┐
                   │                                                              │
                   │    (pausa com interrupt até o colaborador responder) ←──────┘
                   └─ tentativas esgotadas ──→ hand_over_to_hr → FIM
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from sinergia.agents.reception.classifier import classify_document
from sinergia.agents.reception.goal import evaluate_dossier
from sinergia.agents.reception.inspection import FileInspector
from sinergia.agents.reception.messages import MessageComposer
from sinergia.agents.reception.models import Assessment, FileReport, Submission
from sinergia.core.clock import Clock
from sinergia.core.domain import CaseStatus, DocumentType
from sinergia.core.rules import RuleCatalog
from sinergia.core.state import CaseState
from sinergia.data.audit import AuditLog
from sinergia.data.file_store import FileStore
from sinergia.data.intakes import Intake, IntakeRepository

ACTOR = "agente_1_recepcao"
Route = Literal["store_dossier", "ask_employee", "hand_over_to_hr"]


def new_protocol(moment: datetime) -> str:
    """Gera um protocolo legível: SNG-AAAAMMDD-XXXXXX."""
    return f"SNG-{moment:%Y%m%d}-{secrets.token_hex(3).upper()}"


@dataclass(frozen=True)
class ReceptionDeps:
    """Dependências injetadas no Agente 1."""

    rules: RuleCatalog
    inspector: FileInspector
    files: FileStore
    intakes: IntakeRepository
    audit: AuditLog
    composer: MessageComposer
    clock: Clock
    protocol_factory: Callable[[datetime], str] = new_protocol


class ReceptionNodes:
    """Nós do subgrafo; cada um faz uma etapa do ciclo do agente."""

    def __init__(self, deps: ReceptionDeps) -> None:
        self._deps = deps

    def perceive(self, state: CaseState) -> dict[str, Any]:
        """Percepção: inspeciona o arquivo e lê o tipo do documento."""
        submission = Submission.model_validate(state["submission"])
        report = self._deps.inspector.inspect(submission.file_path)
        detected = classify_document(report.text)
        return {"file_report": report.model_dump(mode="json"), "detected_type": detected.value}

    def decide(self, state: CaseState) -> dict[str, Any]:
        """Decisão: compara o dossiê com o objetivo e registra a avaliação."""
        assessment = evaluate_dossier(
            Submission.model_validate(state["submission"]),
            FileReport.model_validate(state["file_report"]),
            DocumentType(state["detected_type"]),
            self._deps.rules.reception,
            self._deps.clock().date(),
        )
        self._deps.audit.record(
            ACTOR,
            "avaliacao_do_dossie",
            state["session_id"],
            assessment.rule_hits,
            {"faltando": [item.value for item in assessment.missing]},
        )
        missing = [item.value for item in assessment.missing]
        return {"assessment": assessment.model_dump(mode="json"), "missing": missing}

    def route(self, state: CaseState) -> Route:
        """Escolhe a próxima ação a partir da avaliação."""
        if Assessment.model_validate(state["assessment"]).complete:
            return "store_dossier"
        limit = self._deps.rules.reception.max_resubmission_attempts
        if state.get("resubmissions", 0) >= limit:
            return "hand_over_to_hr"
        return "ask_employee"

    def ask_employee(self, state: CaseState) -> dict[str, Any]:
        """Ação: monta o pedido do que falta (roda uma vez por pedido)."""
        assessment = Assessment.model_validate(state["assessment"])
        message = self._deps.composer.request_missing(assessment.missing)
        self._deps.audit.record(
            ACTOR, "pedido_ao_colaborador", state["session_id"], assessment.rule_hits
        )
        return {"message": message, "status": CaseStatus.AWAITING_EMPLOYEE.value}

    def wait_for_employee(self, state: CaseState) -> dict[str, Any]:
        """Pausa o caso até o colaborador responder e junta a resposta ao envio."""
        reply = interrupt(
            {"kind": "employee", "message": state["message"], "missing": state["missing"]}
        )
        current = Submission.model_validate(state["submission"])
        answer = Submission.model_validate(reply)
        if answer.file_path and answer.file_path != current.file_path:
            self._deps.files.discard(_as_path(current.file_path))
        merged = current.merge(answer)
        return {
            "submission": merged.model_dump(mode="json"),
            "resubmissions": state.get("resubmissions", 0) + 1,
        }

    def store_dossier(self, state: CaseState) -> dict[str, Any]:
        """Ação final: arquiva o original, cria a linha de entrada e o protocolo."""
        assessment = Assessment.model_validate(state["assessment"])
        late = assessment.late_delivery
        pendency = ("entrega_fora_do_prazo", "R03") if late else None
        intake = self._finish(state, CaseStatus.RECEIVED, "dossie_recebido", pendency)
        document_type = assessment.document_type or DocumentType.UNKNOWN
        message = self._deps.composer.confirm_receipt(intake.protocol, document_type, late)
        return {
            "status": intake.status.value,
            "protocol": intake.protocol,
            "message": message,
            "missing": [],
        }

    def hand_over_to_hr(self, state: CaseState) -> dict[str, Any]:
        """Exceção: o colaborador não completou o envio; o RH assume."""
        pendency = ("envio_incompleto", None)
        intake = self._finish(state, CaseStatus.PENDING_HR, "encaminhado_ao_rh", pendency)
        message = self._deps.composer.hand_over_to_hr(intake.protocol)
        return {"status": intake.status.value, "protocol": intake.protocol, "message": message}

    def _finish(
        self,
        state: CaseState,
        status: CaseStatus,
        action: str,
        pendency: tuple[str, str | None] | None,
    ) -> Intake:
        """Grava a linha de entrada, abre a pendência para o RH e registra na auditoria."""
        now = self._deps.clock()
        assessment = Assessment.model_validate(state["assessment"])
        intake = self._save_intake(state, now, status, assessment)
        if pendency is not None:
            kind, rule_id = pendency
            self._deps.intakes.open_pendency(intake.protocol, kind, "RH", rule_id, now)
        self._deps.audit.record(
            ACTOR, action, intake.protocol, assessment.rule_hits, {"sessao": state["session_id"]}
        )
        return intake

    def _save_intake(
        self, state: CaseState, now: datetime, status: CaseStatus, assessment: Assessment
    ) -> Intake:
        """Arquiva o arquivo (se houver um utilizável) e grava a linha de entrada."""
        protocol = self._deps.protocol_factory(now)
        submission = Submission.model_validate(state["submission"])
        report = FileReport.model_validate(state["file_report"])
        intake = Intake(
            protocol=protocol,
            session_id=state["session_id"],
            received_at=now,
            status=status,
            mime_type=report.mime,
            attempts=state.get("resubmissions", 0) + 1,
            rules_version=self._deps.rules.version,
            **_submission_fields(submission, assessment),
            **self._archive(submission, report, protocol, now),
        )
        self._deps.intakes.add(intake)
        return intake

    def _archive(
        self, submission: Submission, report: FileReport, protocol: str, now: datetime
    ) -> dict[str, str]:
        """Move o arquivo para o repositório definitivo, quando ele é utilizável."""
        if not (report.present and report.mime and submission.file_path):
            self._deps.files.discard(_as_path(submission.file_path))
            return {}
        stored = self._deps.files.archive(Path(submission.file_path), protocol, report.mime, now)
        return {"file_path": stored.path, "file_sha256": stored.sha256}


def _submission_fields(submission: Submission, assessment: Assessment) -> dict[str, Any]:
    """Campos da linha de entrada que vêm do envio e da avaliação."""
    return {
        "employee_id": submission.employee_id,
        "channel": submission.channel,
        "document_type": assessment.document_type,
        "absence_start": submission.absence_start,
        "late_delivery": assessment.late_delivery,
        "original_name": submission.original_name,
    }


def _as_path(value: str | None) -> Path | None:
    """Converte um caminho opcional em ``Path``."""
    return Path(value) if value else None


def build_reception_graph(
    deps: ReceptionDeps, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Monta e compila o subgrafo do Agente 1 (sem checkpointer quando vira nó do grafo do caso)."""
    nodes = ReceptionNodes(deps)
    graph = StateGraph(CaseState)
    graph.add_node("perceive", nodes.perceive)
    graph.add_node("decide", nodes.decide)
    graph.add_node("ask_employee", nodes.ask_employee)
    graph.add_node("wait_for_employee", nodes.wait_for_employee)
    graph.add_node("store_dossier", nodes.store_dossier)
    graph.add_node("hand_over_to_hr", nodes.hand_over_to_hr)
    graph.add_edge(START, "perceive")
    graph.add_edge("perceive", "decide")
    graph.add_conditional_edges("decide", nodes.route)
    graph.add_edge("ask_employee", "wait_for_employee")
    graph.add_edge("wait_for_employee", "perceive")
    graph.add_edge("store_dossier", END)
    graph.add_edge("hand_over_to_hr", END)
    return graph.compile(checkpointer=checkpointer)
