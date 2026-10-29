"""Prazos legais que seguem direto para o escalonamento (R10 e R11).

R10: a partir do 16º dia de afastamento o benefício é do INSS (Lei 8.213/1991, art. 60).
R11: atestados pela mesma doença em até 60 dias, somando mais de 15 dias
(Decreto 3.048/1999, art. 75). "Mesma doença" usa a categoria do CID (3 primeiros
caracteres) e só é avaliada quando o CID consta nos documentos.
"""

from datetime import timedelta

from sinergia.agents.processing.models import Escalation
from sinergia.core.domain import AbsenceStatus
from sinergia.core.rules import ProcessingRules
from sinergia.data.absences import Absence


def legal_escalations(
    absence: Absence, others: list[Absence], rules: ProcessingRules
) -> list[Escalation]:
    """Encaminhamentos com prazo legal disparados por este afastamento."""
    if (absence.days or 0) > rules.inss_threshold_days:
        return [_inss(absence.days or 0)]
    total = (absence.days or 0) + _same_cause_days(absence, others, rules)
    if absence.cid and total > rules.inss_threshold_days:
        return [_same_cause(total, rules.same_cause_window_days)]
    return []


def _inss(days: int) -> Escalation:
    """R10: afastamento longo segue para o INSS."""
    return Escalation(
        rule_id="R10",
        kind="encaminhamento_inss",
        target_area="RH/DP",
        reason=f"Afastamento de {days} dias: a partir do 16º dia o benefício é do INSS.",
    )


def _same_cause(total: int, window: int) -> Escalation:
    """R11: mesma doença somando mais de 15 dias na janela."""
    return Escalation(
        rule_id="R11",
        kind="soma_mesma_doenca",
        target_area="RH/DP e médico do trabalho",
        reason=f"Mesma categoria de CID somando {total} dias em {window} dias.",
    )


def _same_cause_days(absence: Absence, others: list[Absence], rules: ProcessingRules) -> int:
    """Dias de afastamentos válidos com a mesma categoria de CID, dentro da janela."""
    if not (absence.cid and absence.start_date):
        return 0
    window_start = absence.start_date - timedelta(days=rules.same_cause_window_days)
    return sum(
        other.days or 0
        for other in others
        if other.status is AbsenceStatus.VALID
        and other.cid
        and other.cid[:3] == absence.cid[:3]
        and other.start_date
        and window_start <= other.start_date <= absence.start_date
    )
