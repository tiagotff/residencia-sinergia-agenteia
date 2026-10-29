"""Percepção do Agente 4 (R10–R13 e alertas) e o texto escrito para cada destino."""

from datetime import date, datetime, timedelta

from sinergia.agents.escalation.demands import alert_demands, case_demands
from sinergia.agents.escalation.summary import compose
from sinergia.core.domain import AbsenceStatus
from sinergia.core.rules import RuleCatalog
from sinergia.data.absences import Absence
from sinergia.data.alerts import StoredAlert

TODAY = date(2026, 10, 28)


def _absence(days: int, cid: str | None = None) -> Absence:
    return Absence(
        protocol="SNG-1",
        session_id="s",
        employee_id="1001",
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 27) + timedelta(days=days - 1),
        days=days,
        cid=cid,
        status=AbsenceStatus.VALID,
        extraction_method="regex",
        rules_version="t",
        updated_at=datetime(2026, 10, 28),
    )


def _rules(demands) -> list[str]:
    return [demand.rule_id for demand in demands]


def test_long_absence_has_inss_deadline_on_day_16_and_return_exam(rules: RuleCatalog) -> None:
    demands = case_demands(_absence(35), [{"rule_id": "R10"}], rules, TODAY)
    assert _rules(demands) == ["R10", "R12"]
    assert demands[0].deadline == date(2026, 11, 11)
    assert demands[1].deadline == date(2026, 12, 1)
    assert demands[1].facts["retorno"] == "01/12/2026"


def test_short_absence_without_occupational_cid_has_no_demand(rules: RuleCatalog) -> None:
    assert case_demands(_absence(3, "J11"), [], rules, TODAY) == []


def test_injury_cid_is_an_occupational_indication(rules: RuleCatalog) -> None:
    [demand] = case_demands(_absence(5, "S62.5"), [], rules, TODAY)
    assert (demand.rule_id, demand.health_detail, demand.deadline) == (
        "R13",
        "S62",
        date(2026, 10, 29),
    )


def test_cid_reaches_only_health_destinations(rules: RuleCatalog) -> None:
    [demand] = case_demands(_absence(5, "S62.5"), [], rules, TODAY)
    assert "S62" in compose(demand, "sesmt", rules.escalation)
    assert "S62" not in compose(demand, "rh_dp", rules.escalation)


def _alert(rule_id: str, scope_type: str, scope: str, cid: str | None) -> StoredAlert:
    return StoredAlert(
        id=7,
        rule_id=rule_id,
        scope_type=scope_type,
        scope=scope,
        period_start=TODAY,
        period_end=TODAY,
        metric="m",
        value=13,
        threshold=12,
        group_size=1,
        sensitive=bool(cid),
        explanation=f"Texto do alerta com grupo {cid}.",
        details={"grupo_cid": cid} if cid else {},
        rules_version="t",
        created_at=datetime(2026, 10, 28),
    )


def test_alerts_never_reidentify_people(rules: RuleCatalog) -> None:
    group, person = alert_demands(
        [_alert("A02", "setor", "Câmara Fria", "M54"), _alert("A04", "colaborador", "P-1", "M75")],
        rules,
        TODAY,
    )
    assert (group.max_detail, group.subject) == ("agregado", "setor Câmara Fria")
    assert (person.max_detail, person.subject) == ("pseudonimizado", "P-1")


def test_health_alert_text_for_hr_has_no_cid(rules: RuleCatalog) -> None:
    [demand] = alert_demands([_alert("A04", "colaborador", "P-1", "M75")], rules, TODAY)
    assert "M75" in compose(demand, "medico_trabalho", rules.escalation)
    text = compose(demand, "rh_dp", rules.escalation)
    assert "M75" not in text and "P-1" in text
