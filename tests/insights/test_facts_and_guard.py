"""Fatos agregados, relatório padrão e conferência de privacidade (I01)."""

import re

from sinergia.core.rules import RuleCatalog
from sinergia.insights.facts import facts_text
from sinergia.insights.guard import check_report
from sinergia.insights.template import template_report
from tests.conftest import NOW


def test_facts_are_aggregated_and_free_of_personal_data(make_app) -> None:
    app = make_app()
    facts = app.insights.facts(NOW.date())
    text = facts_text(facts)
    assert facts.employees == 100 and facts.suppressed_groups == 1
    assert facts.hidden_groups == ["Diretoria"] and "Diretoria" not in text
    logistica = next(s for s in facts.sectors if s["setor"] == "Logística")
    assert logistica["taxa_semana_pct"] == 9.6 and len(logistica["serie_pct"]) == 8
    assert {a["regra"] for a in facts.alerts} == {"A01", "A02", "A03"}
    assert not re.search(r"P-[0-9a-f]{10}|M54|M75|ADM001|LOG0", text)
    assert "função Operador de empilhadeira" in text
    assert facts.tasks["por_situacao"] == {"aberto": 9}


def test_template_report_passes_the_privacy_check(make_app, rules: RuleCatalog) -> None:
    app = make_app()
    facts = app.insights.facts(NOW.date())
    report = template_report(facts)
    ids = [e.employee_id for e in app.employees.active()]
    assert check_report(report, facts_text(facts), (ids, facts.hidden_groups), rules) == []
    assert "## Sugestões de ação preventiva" in report and "9,6%" in report


def test_guard_catches_each_kind_of_leak(rules: RuleCatalog) -> None:
    facts = "Período: 22/10/2026 a 28/10/2026.\n- Logística (40 pessoas): 9,6%"
    forbidden = (["LOG001"], ["Diretoria"])

    def issues(text: str) -> list[str]:
        return check_report(text, facts, forbidden, rules)

    assert issues("A Logística ficou em 9,6% (40 pessoas), alertas A01 e A02.") == []
    assert issues("Há 3 setores e 2 alertas.") == []
    assert "pseudônimo" in issues("O colaborador P-1c9a902c49 voltou.")[0]
    assert "CID: M54" in issues("Casos de M54 na Câmara Fria.")[0]
    assert "matrícula" in issues("LOG001 faltou.")[0]
    assert "grupo pequeno" in issues("A Diretoria teve casos.")[0]
    assert "estigmatizante" in issues("Funcionários faltosos na Logística.")[0]
    assert "12,3" in issues("A taxa chegou a 12,3%.")[0]
