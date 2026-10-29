"""Avaliação do objetivo do Agente 1: o dossiê de entrada está completo e válido?

Função pura: mesma entrada, mesma decisão. Aplica R01, R02 e R03.
"""

from datetime import date

from sinergia.agents.reception.models import (
    Assessment,
    FileIssue,
    FileReport,
    MissingItem,
    Submission,
)
from sinergia.core.domain import DocumentType
from sinergia.core.rules import ReceptionRules

_FORMAT_ISSUES = {FileIssue.UNSUPPORTED_FORMAT, FileIssue.TOO_LARGE, FileIssue.TOO_MANY_PAGES}


def evaluate_dossier(
    submission: Submission,
    report: FileReport,
    detected_type: DocumentType,
    rules: ReceptionRules,
    today: date,
) -> Assessment:
    """Compara o que foi enviado com o objetivo e lista o que falta."""
    document_type = resolve_document_type(submission.declared_type, detected_type)
    missing = [
        *_file_items(report),
        *_type_items(document_type, rules),
        *_metadata_items(submission),
    ]
    late, days = _check_deadline(submission.absence_start, today, rules)
    hits = {item.rule_id for item in missing if item.rule_id} | ({"R03"} if late else set())
    return Assessment(
        document_type=document_type,
        missing=missing,
        rule_hits=sorted(hits),
        late_delivery=late,
        days_since_start=days,
    )


def resolve_document_type(
    declared: DocumentType | None, detected: DocumentType
) -> DocumentType | None:
    """O tipo lido no documento prevalece; sem texto, vale o declarado."""
    if detected is not DocumentType.UNKNOWN:
        return detected
    return declared


def _file_items(report: FileReport) -> list[MissingItem]:
    """Traduz os problemas do arquivo em itens pendentes (R02)."""
    issues = set(report.issues)
    if FileIssue.MISSING in issues:
        return [MissingItem.FILE]
    if issues & _FORMAT_ISSUES:
        return [MissingItem.FILE_FORMAT]
    if issues:
        return [MissingItem.FILE_UNREADABLE]
    return []


def _type_items(document_type: DocumentType | None, rules: ReceptionRules) -> list[MissingItem]:
    """Confere se o tipo é conhecido e está na lista aceita (R01)."""
    if document_type is None or document_type is DocumentType.UNKNOWN:
        return [MissingItem.DOCUMENT_TYPE]
    if document_type not in rules.accepted_document_types:
        return [MissingItem.DOCUMENT_TYPE_NOT_ACCEPTED]
    return []


def _metadata_items(submission: Submission) -> list[MissingItem]:
    """Informações do colaborador necessárias para abrir o protocolo."""
    items = []
    if not submission.employee_id:
        items.append(MissingItem.EMPLOYEE_ID)
    if submission.absence_start is None:
        items.append(MissingItem.ABSENCE_START)
    return items


def _check_deadline(
    absence_start: date | None, today: date, rules: ReceptionRules
) -> tuple[bool, int | None]:
    """R03: a entrega passou do prazo da política? Não bloqueia, só sinaliza."""
    if absence_start is None:
        return False, None
    days = (today - absence_start).days
    return days > rules.delivery_deadline_days, days
