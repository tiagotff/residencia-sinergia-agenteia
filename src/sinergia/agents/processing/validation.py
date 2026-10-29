"""Regras de validação do Agente 2 (R04–R08), em Python puro e explicáveis.

Cada violação aponta a regra e os campos envolvidos. Depois que um profissional aprova o
caso, R06 (CRM) e R08 (confiança) deixam de bloquear: a conferência humana as substitui.
"""

from collections.abc import Sequence
from datetime import date, timedelta

from sinergia.agents.processing.models import CrmCheck, CrmStatus, Extraction, Validation, Violation
from sinergia.core.domain import DocumentType
from sinergia.core.rules import ProcessingRules
from sinergia.data.absences import Absence
from sinergia.data.vacations import Vacation


def validate_absence(
    extraction: Extraction,
    crm_check: CrmCheck,
    others: list[Absence],
    rules: ProcessingRules,
    human_approved: bool = False,
    vacations: Sequence[Vacation] = (),
) -> Validation:
    """Aplica R04, R05, R06, R07 e R08 e devolve todas as violações encontradas."""
    violations = [
        *_required_fields(extraction, rules),
        *_coherent_dates(extraction, rules),
        *_overlaps(extraction, others),
        *_vacation_overlaps(extraction, vacations),
    ]
    if not human_approved:
        violations += [*_active_crm(extraction, crm_check), *_confidence(extraction, rules)]
    return Validation(violations=violations)


def _required_fields(extraction: Extraction, rules: ProcessingRules) -> list[Violation]:
    """R04: campos obrigatórios para o tipo de documento."""
    document_type = extraction.document_type or DocumentType.MEDICAL_CERTIFICATE
    required = rules.required_fields.get(document_type, [])
    values = extraction.fields.model_dump()
    missing = [name for name in required if values.get(name) in (None, "", False)]
    if not missing:
        return []
    return [Violation(rule_id="R04", message="Campos obrigatórios ausentes.", fields=missing)]


def _coherent_dates(extraction: Extraction, rules: ProcessingRules) -> list[Violation]:
    """R05: fim não anterior ao início, emissão dentro da tolerância e dias consistentes."""
    fields = extraction.fields
    if fields.start_date is None:
        return []
    found = []
    if fields.end_date and fields.end_date < fields.start_date:
        found.append(("O fim do afastamento é anterior ao início.", ["start_date", "end_date"]))
    tolerance = timedelta(days=rules.issue_after_start_tolerance_days)
    if fields.issue_date and fields.issue_date > fields.start_date + tolerance:
        found.append(
            ("A emissão é posterior ao início além da tolerância.", ["issue_date", "start_date"])
        )
    if _days_mismatch(extraction):
        found.append(("A quantidade de dias não bate com o período.", ["days", "end_date"]))
    return [Violation(rule_id="R05", message=message, fields=names) for message, names in found]


def _days_mismatch(extraction: Extraction) -> bool:
    """Dias e fim informados no documento (não derivados) precisam concordar."""
    fields = extraction.fields
    if "end_date" in extraction.derived or "days" in extraction.derived:
        return False
    if not (fields.start_date and fields.end_date and fields.days):
        return False
    return (fields.end_date - fields.start_date).days + 1 != fields.days


def _active_crm(extraction: Extraction, crm_check: CrmCheck) -> list[Violation]:
    """R06: CRM regular na consulta do CFM (ou na fonte configurada)."""
    if extraction.fields.crm_number is None or crm_check.status is CrmStatus.REGULAR:
        return []
    return [Violation(rule_id="R06", message=crm_check.detail, fields=["crm_number", "crm_uf"])]


def _period(extraction: Extraction) -> tuple[date, date] | None:
    """Início e último dia do afastamento extraído."""
    start = extraction.fields.start_date
    return None if start is None else (start, extraction.fields.end_date or start)


def _overlaps(extraction: Extraction, others: list[Absence]) -> list[Violation]:
    """R07: sem sobreposição com outro afastamento do mesmo colaborador."""
    period = _period(extraction)
    if period is None:
        return []
    start, end = period
    clashes = [
        other.protocol
        for other in others
        if other.start_date and other.start_date <= end and start <= other.last_day
    ]
    if not clashes:
        return []
    message = f"Período sobreposto ao(s) protocolo(s) {', '.join(clashes)}."
    return [Violation(rule_id="R07", message=message, fields=["start_date", "end_date"])]


def _vacation_overlaps(extraction: Extraction, vacations: Sequence[Vacation]) -> list[Violation]:
    """R07: sem sobreposição com férias já registradas."""
    period = _period(extraction)
    if period is None:
        return []
    start, end = period
    clashes = [
        f"{item.start_date:%d/%m/%Y} a {item.end_date:%d/%m/%Y}"
        for item in vacations
        if item.start_date <= end and start <= item.end_date
    ]
    if not clashes:
        return []
    message = f"Período sobreposto às férias de {'; '.join(clashes)}."
    return [Violation(rule_id="R07", message=message, fields=["start_date", "end_date"])]


def _confidence(extraction: Extraction, rules: ProcessingRules) -> list[Violation]:
    """R08: leitura ou campos com confiança abaixo do limiar vão para conferência."""
    return [*_low_ocr(extraction, rules), *_low_fields(extraction, rules)]


def _low_ocr(extraction: Extraction, rules: ProcessingRules) -> list[Violation]:
    """A leitura por OCR como um todo ficou pouco confiável (foto ruim, por exemplo)."""
    score = extraction.ocr_confidence
    if score is None or score >= rules.min_ocr_confidence:
        return []
    message = f"Leitura do documento com baixa confiança ({score:.2f}); conferir no original."
    return [Violation(rule_id="R08", message=message, fields=[])]


def _low_fields(extraction: Extraction, rules: ProcessingRules) -> list[Violation]:
    """Campos extraídos com confiança abaixo do limiar."""
    low = [
        name
        for name, score in extraction.confidence.items()
        if score < rules.min_field_confidence and name not in extraction.human_verified
    ]
    if not low:
        return []
    message = "Extração com baixa confiança; conferir os campos destacados."
    return [Violation(rule_id="R08", message=message, fields=sorted(low))]
