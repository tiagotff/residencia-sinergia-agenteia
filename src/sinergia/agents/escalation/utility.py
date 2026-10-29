"""Decisão do Agente 4 (baseado em utilidade): destino, urgência e nível de detalhe.

Para cada destino possível, testa todas as urgências e níveis de detalhe permitidos e fica
com a alternativa de maior utilidade:

    U = w_competência × competência
        − w_privacidade × custo do detalhe
        − w_urgência × custo da urgência
        − w_prazo × gravidade × (dias de atraso previstos ÷ maior SLA)

Restrições (nunca negociadas pela pontuação):
- o gestor nunca recebe demanda com dado de saúde;
- o detalhe fica entre o mínimo para agir e o máximo que a origem permite.

Recebem tarefa os destinos com U >= min_utility; a melhor sempre recebe (é a principal).
"""

from datetime import date

from sinergia.agents.escalation.models import Demand, Proposal
from sinergia.core.rules import EscalationRules

MANAGER = "gestor"


def propose(demand: Demand, rules: EscalationRules, today: date) -> list[Proposal]:
    """Propostas para a demanda, da maior para a menor utilidade."""
    best = [
        option
        for destination in rules.demands[demand.rule_id].competence
        if (option := best_for(demand, destination, rules, today)) is not None
    ]
    best.sort(key=lambda item: (-item.utility, item.destination))
    if not best:
        return []
    chosen = [best[0]] + [p for p in best[1:] if p.utility >= rules.min_utility]
    chosen[0] = chosen[0].model_copy(update={"primary": True})
    return chosen


def best_for(
    demand: Demand, destination: str, rules: EscalationRules, today: date
) -> Proposal | None:
    """Melhor combinação de urgência e detalhe para um destino (None se proibido)."""
    if not allowed(demand, destination, rules):
        return None
    options = [
        score(demand, destination, urgency, detail, rules, today)
        for urgency in rules.urgencies
        for detail in detail_range(demand, rules)
    ]
    return max(options, key=lambda item: item.utility, default=None)


def allowed(demand: Demand, destination: str, rules: EscalationRules) -> bool:
    """Restrição de privacidade: gestor só vê ausência, nunca saúde."""
    return not (destination == MANAGER and rules.demands[demand.rule_id].health)


def detail_range(demand: Demand, rules: EscalationRules) -> list[str]:
    """Níveis entre o mínimo para agir e o máximo permitido pela origem."""
    levels = list(rules.detail_levels)
    low = levels.index(rules.demands[demand.rule_id].min_detail)
    high = levels.index(demand.max_detail)
    return levels[low : high + 1] or [levels[high]]


def score(
    demand: Demand,
    destination: str,
    urgency: str,
    detail: str,
    rules: EscalationRules,
    today: date,
) -> Proposal:
    """Calcula U e guarda cada parcela, para a decisão ser explicável."""
    kind, weights = rules.demands[demand.rule_id], rules.weights
    slack = (demand.deadline - today).days if demand.deadline else rules.max_sla
    late = max(0, rules.urgencies[urgency].sla_days - max(slack, 0))
    parts = {
        "competencia": weights["competence"] * kind.competence[destination],
        "privacidade": -weights["privacy"] * rules.detail_levels[detail],
        "urgencia": -weights["urgency"] * rules.urgencies[urgency].cost,
        "prazo": -weights["deadline"] * kind.severity * late / rules.max_sla,
    }
    breakdown = {name: round(value, 4) for name, value in parts.items()}
    breakdown["folga_dias"] = slack
    utility = round(sum(parts.values()), 4)
    return Proposal(
        destination=destination,
        urgency=urgency,
        detail=detail,
        utility=utility,
        breakdown=breakdown,
    )
