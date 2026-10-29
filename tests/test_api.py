"""Testes da API HTTP da recepção."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sinergia.api.app import create_app
from sinergia.bootstrap import Container


@pytest.fixture
def client(container: Container) -> TestClient:
    return TestClient(create_app(container))


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_submit_reply_and_query_protocol(client: TestClient, samples: Path) -> None:
    pdf = (samples / "atestado_medico.pdf").read_bytes()
    first = client.post(
        "/reception/submissions",
        data={"employee_id": "1001"},
        files={"file": ("atestado.pdf", pdf, "application/pdf")},
    ).json()
    assert first["status"] == "aguardando_colaborador"
    assert first["missing"] == ["data_inicio"]

    final = client.post(
        f"/reception/submissions/{first['session_id']}/reply",
        data={"absence_start": "2026-10-27"},
    ).json()
    assert final["status"] == "recebido"

    body = client.get(f"/reception/intakes/{final['protocol']}").json()
    assert body["intake"]["document_type"] == "atestado_medico"
    assert "file_path" not in body["intake"]
    assert body["pendencies"] == []


def test_reply_errors(client: TestClient) -> None:
    assert client.post("/reception/submissions/nao-existe/reply").status_code == 404
    assert client.get("/reception/intakes/SNG-0").status_code == 404


def test_invalid_document_type_is_rejected(client: TestClient) -> None:
    response = client.post("/reception/submissions", data={"declared_type": "laudo"})
    assert response.status_code == 422


def test_review_queue_and_decision(client: TestClient, samples: Path) -> None:
    pdf = (samples / "atestado_datas_incoerentes.pdf").read_bytes()
    created = client.post(
        "/reception/submissions",
        data={"employee_id": "1001", "absence_start": "2026-10-27"},
        files={"file": ("atestado.pdf", pdf, "application/pdf")},
    ).json()
    protocol = created["protocol"]

    [case] = client.get("/review/cases").json()
    assert case["protocol"] == protocol
    assert case["payload"]["violations"][0]["rule_id"] == "R05"

    bad = client.post(
        f"/review/cases/{protocol}/decision",
        json={"decision": "aprovar", "reviewer": "Ana (RH)", "corrections": {"days": "x"}},
    )
    assert bad.status_code == 422

    decided = client.post(
        f"/review/cases/{protocol}/decision",
        json={
            "decision": "aprovar",
            "reviewer": "Ana (RH)",
            "corrections": {"issue_date": "27/10/2026"},
        },
    ).json()
    assert decided["status"] == "valido"

    absence = client.get(f"/absences/{protocol}").json()
    assert absence["reviewed_by"] == "Ana (RH)"
    assert "cid" not in absence and absence["cid_present"] is False
    assert client.get(f"/review/cases/{protocol}").status_code == 409


def test_unknown_correction_field_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/review/cases/SNG-0/decision",
        json={"decision": "aprovar", "reviewer": "Ana", "corrections": {"salario": 1}},
    )
    assert response.status_code == 422


def test_vacation_routes(client: TestClient, samples: Path) -> None:
    body = {"employee_id": "7007", "start_date": "26/10/2026", "end_date": "09/11/2026"}
    assert client.post("/vacations", json=body).json() == {"added": True}
    csv_bytes = (samples / "ferias.csv").read_bytes()
    imported = client.post(
        "/vacations/import", files={"file": ("ferias.csv", csv_bytes, "text/csv")}
    ).json()
    assert imported == {"imported": 1}
    assert len(client.get("/vacations/7007").json()) == 1
    bad = client.post("/vacations/import", files={"file": ("x.csv", b"a;b\n1;2\n", "text/csv")})
    assert bad.status_code == 422
