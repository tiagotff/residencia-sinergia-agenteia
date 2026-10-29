"""Texto de cada encaminhamento, escrito para o destino (sem LLM).

O grupo de CID só aparece para destinos de saúde (SESMT e médico do trabalho). Para os
demais, alertas de saúde chegam sem o detalhe clínico, com a indicação de onde ele está.
"""

from collections.abc import Callable

from sinergia.agents.escalation.models import Demand
from sinergia.core.rules import EscalationRules

_HEALTH_ONLY = "Detalhes de saúde com o SESMT/médico do trabalho."


def compose(demand: Demand, destination: str, rules: EscalationRules) -> str:
    """Resumo da demanda para o destino, respeitando o mínimo necessário."""
    health_view = destination in rules.health_destinations
    text = _TEXTS[demand.rule_id](demand, health_view)
    if health_view and demand.health_detail and demand.rule_id in _CASE_RULES:
        text += f" Grupo de CID: {demand.health_detail}."
    return text


def _r10(demand: Demand, _: bool) -> str:
    """R10: afastamento longo vai ao INSS."""
    f = demand.facts
    return (
        f"Colaborador {demand.subject} (protocolo {demand.source_ref}) afastado por {f['dias']} "
        f"dias a partir de {f['inicio']}: a partir do 16º dia o benefício é do INSS. "
        f"Encaminhar ao INSS (Lei 8.213/1991, art. 60)."
    )


def _r11(demand: Demand, _: bool) -> str:
    """R11: mesma doença somando mais de 15 dias em 60."""
    return (
        f"Colaborador {demand.subject} (protocolo {demand.source_ref}): atestados pela mesma "
        f"doença somam mais de 15 dias em 60 dias. Encaminhar ao INSS (Decreto 3.048/1999, "
        f"art. 75) e avaliar com o médico do trabalho."
    )


def _r12(demand: Demand, _: bool) -> str:
    """R12: exame de retorno antes de reassumir."""
    f = demand.facts
    return (
        f"Colaborador {demand.subject} (protocolo {demand.source_ref}) afastado por {f['dias']} "
        f"dias, com retorno previsto em {f['retorno']}: agendar o exame de retorno ao trabalho "
        f"antes de reassumir a função (NR-7, item 7.5.9)."
    )


def _r13(demand: Demand, _: bool) -> str:
    """R13: indício de origem ocupacional; a decisão sobre a CAT é humana."""
    return (
        f"Afastamento do colaborador {demand.subject} (protocolo {demand.source_ref}) com "
        f"indício de origem ocupacional. Avaliar a emissão de CAT, que vence no 1º dia útil "
        f"seguinte à ocorrência (Lei 8.213/1991, art. 22)."
    )


def _alert(demand: Demand, health_view: bool) -> str:
    """A01–A04: a explicação do Agente 3, sem dado de saúde para quem não é da saúde."""
    if health_view or not demand.health_detail:
        return f"{demand.source_ref}: {demand.facts['explicacao']}"
    return f"{demand.source_ref} sobre {demand.subject}. {_HEALTH_ONLY}"


_CASE_RULES = {"R11", "R13"}
_TEXTS: dict[str, Callable[[Demand, bool], str]] = {
    "R10": _r10,
    "R11": _r11,
    "R12": _r12,
    "R13": _r13,
    "A01": _alert,
    "A02": _alert,
    "A03": _alert,
    "A04": _alert,
}
