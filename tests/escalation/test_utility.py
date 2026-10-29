"""Função de utilidade do Agente 4: destino, urgência e detalhe."""

from datetime import date, timedelta

import pytest

from sinergia.agents.escalation.models import Demand
from sinergia.agents.escalation.utility import best_for, propose
from sinergia.core.rules import RuleCatalog

TODAY = date(2026, 10, 28)


def _demand(rule_id: str, days: int | None, detail: str = "individual") -> Demand:
    deadline = TODAY + timedelta(days=days) if days is not None else None
    return Demand(
        key="k", rule_id=rule_id, subject="s", source_ref="r", deadline=deadline, max_detail=detail
    )


def _chosen(rules: RuleCatalog, demand: Demand) -> list[tuple[str, str, bool]]:
    return [(p.destination, p.urgency, p.primary) for p in propose(demand, rules.escalation, TODAY)]


@pytest.mark.parametrize(
    ("slack", "urgency"),
    [(14, "baixa"), (6, "media"), (3, "alta"), (1, "critica"), (-2, "critica")],
)
def test_urgency_follows_the_deadline(rules: RuleCatalog, slack: int, urgency: str) -> None:
    assert _chosen(rules, _demand("R10", slack)) == [("rh_dp", urgency, True)]


def test_same_cause_goes_to_hr_and_occupational_doctor(rules: RuleCatalog) -> None:
    assert [d for d, _, _ in _chosen(rules, _demand("R11", 3))] == ["rh_dp", "medico_trabalho"]


def test_manager_never_receives_health_data(rules: RuleCatalog) -> None:
    for rule_id in ("R11", "R13", "A02", "A04"):
        assert best_for(_demand(rule_id, 3, "agregado"), "gestor", rules.escalation, TODAY) is None
    coverage = _chosen(rules, _demand("A03", 0, "agregado"))
    assert coverage == [("gestor", "critica", True)]


def test_detail_is_the_least_identifiable_that_still_allows_acting(rules: RuleCatalog) -> None:
    [first, *_] = propose(_demand("A04", 5, "pseudonimizado"), rules.escalation, TODAY)
    assert (first.destination, first.detail) == ("medico_trabalho", "pseudonimizado")
    [spike, *_] = propose(_demand("A01", 5, "agregado"), rules.escalation, TODAY)
    assert spike.detail == "agregado"


def test_breakdown_explains_the_utility(rules: RuleCatalog) -> None:
    for proposal in propose(_demand("R12", 25), rules.escalation, TODAY):
        parts = sum(v for k, v in proposal.breakdown.items() if k != "folga_dias")
        assert round(parts, 4) == proposal.utility
        assert proposal.breakdown["folga_dias"] == 25


def test_return_exam_reaches_sesmt_doctor_and_manager(rules: RuleCatalog) -> None:
    chosen = _chosen(rules, _demand("R12", 25))
    assert chosen[0] == ("sesmt", "baixa", True)
    assert {d for d, _, _ in chosen} == {"sesmt", "medico_trabalho", "gestor"}
