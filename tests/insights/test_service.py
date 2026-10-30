"""Serviço de insights: crew aprovada, barrada ou ausente, aprovação humana, CLI e API."""

import pytest
from fastapi.testclient import TestClient

from sinergia.api.app import create_app
from sinergia.cli import main
from sinergia.core.errors import SessionStateError
from sinergia.data.reports import ReportStatus
from sinergia.insights.crew import CrewResult, parse_verdict
from tests.conftest import NOW
from tests.insights.conftest import FakeCrew

GOOD = "# Relatório\n\nA Logística ficou em 9,6% na semana (40 pessoas). Rever a escala."


def test_without_crew_the_template_report_is_used(make_app) -> None:
    report = make_app().insights.run(NOW.date())
    assert (report.method, report.status) == ("modelo", ReportStatus.DRAFT)
    assert report.issues == ["crew: não configurada (LLM ou extra 'insights' ausente)."]
    assert report.content.startswith("# Relatório de saúde ocupacional — 22/10/2026")


def test_approved_crew_text_is_kept(make_app) -> None:
    crew = FakeCrew(CrewResult(approved=True, content=GOOD))
    report = make_app(crew).insights.run(NOW.date())
    assert (report.method, report.content, report.issues) == ("crew", GOOD, [])
    assert "Logística (40 pessoas): 9,6%" in crew.received[0]


@pytest.mark.parametrize(
    ("result", "issue"),
    [
        (CrewResult(approved=True, content="A taxa foi 47,0%."), "Números que não estão"),
        (CrewResult(approved=True, content="Casos de M54 na Câmara Fria."), "CID: M54"),
        (CrewResult(approved=False, content="", reason="cita pessoa"), "devolveu: cita pessoa"),
        (TimeoutError("lento"), "indisponível (TimeoutError)"),
    ],
)
def test_blocked_or_failed_crew_falls_back_to_template(make_app, result, issue) -> None:
    report = make_app(FakeCrew(result)).insights.run(NOW.date())
    assert report.method == "modelo"
    assert issue in report.issues[0]
    assert "## Tendências por setor" in report.content


def test_occupational_doctor_approves_or_returns(make_app) -> None:
    app = make_app()
    first, second = app.insights.run(NOW.date()), app.insights.run(NOW.date())
    approved = app.insights.decide(first.id, True, "Dra. Ana (médica do trabalho)")
    assert (approved.status, approved.decided_by) == (
        ReportStatus.APPROVED,
        "Dra. Ana (médica do trabalho)",
    )
    assert (
        app.insights.decide(second.id, False, "Dra. Ana", "rever ações").status
        is ReportStatus.RETURNED
    )
    with pytest.raises(SessionStateError):
        app.insights.decide(first.id, False, "Dra. Ana")
    actions = [e.action for e in app.audit.list_for(f"relatorio:{first.id}")]
    assert actions == ["relatorio_gerado", "relatorio_aprovado"]


def test_parse_verdict_reads_the_first_line() -> None:
    assert parse_verdict("**APROVADO**\n# Texto") == CrewResult(True, "# Texto")
    assert parse_verdict("DEVOLVIDO: cita CID\n...").reason == "cita CID"
    assert not parse_verdict("Aqui está o relatório").approved


def test_cli_runs_lists_shows_and_approves(make_app, monkeypatch, capsys) -> None:
    app = make_app()
    for key, value in {
        "DATA_DIR": str(app.settings.data_dir),
        "LLM_PROVIDER": "none",
        "CRM_VERIFIER": "local",
    }.items():
        monkeypatch.setenv(key, value)
    assert main(["insights", "run", "--date", "2026-10-28"]) == 0
    assert main(["insights", "list"]) == 0
    assert main(["insights", "show", "1"]) == 0
    assert main(["insights", "approve", "1", "--by", "Dra. Ana"]) == 0
    assert main(["insights", "approve", "1", "--by", "Dra. Ana"]) == 1
    out = capsys.readouterr()
    assert "#1 22/10/2026 a 28/10/2026 [rascunho] (feito por: modelo)" in out.out
    assert "[aprovado]" in out.out and "já foi aprovado" in out.err


def test_api_runs_and_decides(make_app) -> None:
    client = TestClient(create_app(make_app()))
    report = client.post("/insights/run", params={"reference_date": "2026-10-28"}).json()
    assert report["method"] == "modelo" and report["facts"]["employees"] == 100
    assert len(client.get("/insights").json()) == 1
    decided = client.post(
        f"/insights/{report['id']}/decision", json={"approve": True, "by": "Dra. Ana"}
    ).json()
    assert decided["status"] == "aprovado"
    again = client.post(f"/insights/{report['id']}/decision", json={"approve": True, "by": "Dra"})
    assert again.status_code == 409
    assert client.get("/insights/99").status_code == 404
