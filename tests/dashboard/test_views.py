"""Dados do painel por perfil: cada um vê só o que precisa."""

import json
from datetime import date

from sinergia.dashboard import views
from tests.conftest import NOW

REFERENCE = date(2026, 10, 28)


def test_manager_sees_who_is_absent_without_health_data(make_app) -> None:
    data = views.manager_view(make_app(), REFERENCE)
    assert len(data["ausentes"]) == 11
    assert {row["setor"] for row in data["ausentes"]} == {"Logística", "Diretoria"}
    assert set(data["ausentes"][0]) == {"matricula", "setor", "funcao", "turno", "ausente_ate"}
    assert data["cobertura"] == [
        {
            "funcao": "Operador de empilhadeira",
            "equipe": 5,
            "disponiveis": 3,
            "disponivel_pct": 60.0,
        }
    ]
    assert {row["regra"] for row in data["tarefas"]} == {"A01", "A03"}
    assert "M54" not in json.dumps(data, ensure_ascii=False)


def test_manager_can_filter_by_sector(make_app) -> None:
    data = views.manager_view(make_app(), REFERENCE, "Diretoria")
    assert [row["matricula"] for row in data["ausentes"]] == ["DIR001", "DIR002"]
    assert data["cobertura"] == []


def test_hr_overview_counts_and_deadlines(make_app) -> None:
    data = views.hr_overview(make_app(), REFERENCE)
    assert (data["recebidos"], data["afastamentos"], data["automatico_pct"]) == (63, 63, 100.0)
    assert data["fila_revisao"] == 0
    assert [row["regra"] for row in data["tarefas"]] == ["A04"]
    assert "M75" not in data["tarefas"][0]["resumo"]


def test_sesmt_sees_full_alerts_trend_and_reports(make_app) -> None:
    app = make_app()
    app.insights.run(NOW.date())
    data = views.sesmt_view(app, REFERENCE)
    assert {a["grupo_cid"] for a in data["alertas"] if a["regra"] == "A02"} == {"M54"}
    assert data["tendencia"]["semanas"][-1] == "2026-10-28"
    assert "Diretoria" not in data["tendencia"]["series"]
    assert data["tendencia"]["series"]["Logística"][-1] == 9.6
    assert len(data["relatorios"]) == 1


def test_employee_sees_only_their_case(make_app) -> None:
    app = make_app()
    assert views.employee_case(app, "SNG-NAO-EXISTE") is None
    case = views.employee_case(app, "HIST-0001")
    assert case["afastamento"]["situacao"] == "valido"
    assert "cid" not in json.dumps(case)


def test_audit_trail_most_recent_first(make_app) -> None:
    trail = views.audit_trail(make_app(), limit=3)
    assert len(trail) == 3 and trail[0]["action"] == "encaminhamento_confirmado"
