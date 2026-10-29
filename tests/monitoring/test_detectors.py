"""Regras A01–A05 sobre o histórico sintético com padrões plantados."""

from sinergia.agents.monitoring.detectors import detect
from sinergia.agents.monitoring.snapshot import build_snapshot
from sinergia.core.rules import RuleCatalog
from sinergia.synthetic.history import History, build_history, evaluate
from tests.conftest import NOW

SALT = "sal-de-teste"


def _run(history: History, rules: RuleCatalog):
    absences = [record for _, record in _records(history)]
    snapshot = build_snapshot(NOW.date(), history.employees, absences, SALT)
    return detect(snapshot, rules.monitoring, rules.processing)


def _records(history: History):
    from sinergia.synthetic.history import as_records

    return as_records(history, NOW, "teste")


def _by_rule(found, rule_id: str):
    return [alert for alert in found.alerts if alert.rule_id == rule_id]


def test_all_planted_patterns_are_found_without_false_alarms(
    history: History, rules: RuleCatalog
) -> None:
    found = _run(history, rules)
    report = evaluate(found.alerts, sorted(found.suppressed), history, SALT)
    assert report["faltando"] == [] and report["inesperados"] == []
    assert report["precisao"] == report["cobertura"] == 1.0
    assert report["supressao_ok"]


def test_a01_compares_week_with_sector_baseline(history: History, rules: RuleCatalog) -> None:
    [alert] = _by_rule(_run(history, rules), "A01")
    assert alert.scope == "Logística"
    assert alert.value > alert.threshold > (alert.reference or 0)
    assert alert.details["semanas_na_linha_de_base"] == rules.monitoring.baseline_weeks


def test_a01_needs_enough_baseline_weeks(rules: RuleCatalog) -> None:
    history = build_history(NOW.date())
    history.absences = [item for item in history.absences if (NOW.date() - item[1]).days < 20]
    assert _by_rule(_run(history, rules), "A01") == []


def test_a02_is_sensitive_and_reports_only_cid_category(
    history: History, rules: RuleCatalog
) -> None:
    alerts = _by_rule(_run(history, rules), "A02")
    assert {(a.scope_type, a.scope) for a in alerts} == {
        ("setor", "Câmara Fria"),
        ("turno", "manhã"),
    }
    assert all(a.sensitive and a.details["grupo_cid"] == "M54" for a in alerts)


def test_a03_counts_absent_critical_staff(history: History, rules: RuleCatalog) -> None:
    [alert] = _by_rule(_run(history, rules), "A03")
    assert (alert.details["ausentes"], alert.group_size, alert.value) == (2, 5, 0.6)
    assert not alert.sensitive


def test_a04_uses_pseudonym_and_stays_below_inss_limit(
    history: History, rules: RuleCatalog
) -> None:
    [alert] = _by_rule(_run(history, rules), "A04")
    assert alert.scope.startswith("P-") and "ADM001" not in alert.model_dump_json()
    assert rules.monitoring.same_cause_alert_days <= alert.value < 15


def test_a05_hides_small_sector_even_with_a_spike(history: History, rules: RuleCatalog) -> None:
    found = _run(history, rules)
    assert "setor:Diretoria" in found.suppressed
    assert all(alert.scope != "Diretoria" for alert in found.alerts)
