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
