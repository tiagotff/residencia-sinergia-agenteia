"""Agente 3 de ponta a ponta: execução agendada, deduplicação, auditoria, CLI e API."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sinergia.agents.reception.service import ReceptionInput
from sinergia.api.app import create_app
from sinergia.bootstrap import Container
from sinergia.cli import main
from sinergia.core.domain import DocumentType
from sinergia.synthetic.history import History, write_employees_csv
from tests.conftest import NOW, YESTERDAY

REFERENCE = f"monitoramento:{NOW.date().isoformat()}"


def test_run_stores_explained_alerts_once(loaded: Container) -> None:
    first = loaded.monitoring.run(NOW.date())
    assert len(first["created"]) == 5 and first["suppressed"] == ["setor:Diretoria"]
    alerts = loaded.alerts.list()
    assert all(alert.explanation and alert.rules_version for alert in alerts)
    second = loaded.monitoring.run(NOW.date())
    assert (second["created"], second["already_known"]) == ([], 5)
    assert len(loaded.alerts.list()) == 5


def test_audit_lists_rules_but_no_health_data(loaded: Container) -> None:
    loaded.monitoring.run(NOW.date())
    entry = loaded.audit.list_for(REFERENCE)[0]
    assert entry.rule_ids == ["A01", "A02", "A03", "A04", "A05"]
    assert "M54" not in str(entry.details)


def test_without_employees_nothing_is_flagged(app: Container) -> None:
    summary = app.monitoring.run(NOW.date())
    assert (summary["employees"], summary["created"]) == (0, [])


def test_valid_case_triggers_monitoring(app: Container, samples: Path, ocr) -> None:
    from sinergia.bootstrap import Overrides, build_container
    from sinergia.core.clock import fixed_clock

    full = build_container(app.settings, Overrides(clock=fixed_clock(NOW), ocr=ocr))
    data = ReceptionInput(
        file_name="atestado_medico.pdf",
        content=(samples / "atestado_medico.pdf").read_bytes(),
        employee_id="1001",
        absence_start=YESTERDAY,
        declared_type=DocumentType.MEDICAL_CERTIFICATE,
    )
    full.reception.start(data)
    assert full.audit.list_for(REFERENCE), "o Agente 3 deveria rodar após um caso válido"


def test_cli_imports_runs_and_lists(
    app: Container, history: History, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setenv("DATA_DIR", str(app.settings.data_dir))
    monkeypatch.setenv("LLM_PROVIDER", "none")
    monkeypatch.setenv("CRM_VERIFIER", "local")
    csv_path = write_employees_csv(history, tmp_path / "colaboradores.csv")
    assert main(["employees", "import", str(csv_path)]) == 0
    assert main(["monitor", "run", "--date", NOW.date().isoformat()]) == 0
    assert main(["alerts", "list"]) == 0
    output = capsys.readouterr().out
    assert "100 colaborador(es) importado(s)." in output
    assert "Alertas novos: 0" in output and "Nenhum alerta." in output


def test_api_hides_cid_from_management(loaded: Container) -> None:
    client = TestClient(create_app(loaded))
    assert (
        len(
            client.post("/monitoring/run", params={"reference_date": "2026-10-28"}).json()[
                "created"
            ]
        )
        == 5
    )
    management = client.get("/alerts").json()
    assert "M54" not in str(management)
    sesmt = client.get("/alerts", params={"audience": "sesmt"}).json()
    assert "M54" in str(sesmt)
    assert client.get("/alerts", params={"audience": "todos"}).status_code == 422


def test_api_imports_employees(app: Container, history: History, tmp_path: Path) -> None:
    client = TestClient(create_app(app))
    csv_path = write_employees_csv(history, tmp_path / "colaboradores.csv")
    response = client.post(
        "/employees/import", files={"file": ("c.csv", csv_path.read_bytes(), "text/csv")}
    )
    assert response.json() == {"imported": 100}
    bad = client.post("/employees/import", files={"file": ("c.csv", b"a;b\n1;2\n", "text/csv")})
    assert bad.status_code == 422


def test_next_day_run_does_not_repeat_a_continuing_pattern(loaded: Container) -> None:
    loaded.monitoring.run(NOW.date())
    next_day = loaded.monitoring.run(NOW.date() + timedelta(days=1))
    assert next_day["created"] == []
    assert len(loaded.alerts.list()) == 5


def test_closed_alert_lets_a_new_one_be_created(loaded: Container) -> None:
    loaded.monitoring.run(NOW.date())
    with loaded.database.connect() as conn:
        conn.execute("UPDATE alerts SET status = 'encerrado' WHERE rule_id = 'A01'")
    created = loaded.monitoring.run(NOW.date() + timedelta(days=1))["created"]
    assert [key.split("|")[0] for key in created] == ["A01"]
