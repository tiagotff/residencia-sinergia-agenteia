"""Testes ponta a ponta do Agente 1 sobre o subgrafo LangGraph."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from sinergia.agents.reception.service import ReceptionInput
from sinergia.bootstrap import Container, build_container
from sinergia.core.clock import fixed_clock
from sinergia.core.domain import CaseStatus, DocumentType
from sinergia.core.errors import NotFoundError, SessionStateError
from sinergia.core.settings import Settings
from tests.conftest import NOW, YESTERDAY

MakeInput = Callable[..., ReceptionInput]


def _actions(container: Container, reference: str) -> list[str]:
    return [entry.action for entry in container.audit.list_for(reference)]


def test_complete_first_submission_gets_protocol(
    container: Container, make_input: MakeInput
) -> None:
    data = make_input("atestado_medico.pdf", employee_id="1001", absence_start=YESTERDAY)
    result = container.reception.start(data)

    assert result.status is CaseStatus.RECEIVED
    assert result.protocol and result.protocol.startswith("SNG-20261028-")
    intake = container.intakes.get(result.protocol)
    assert intake.document_type is DocumentType.MEDICAL_CERTIFICATE
    assert intake.attempts == 1
    assert intake.rules_version == container.rules.version
    assert Path(intake.file_path).exists()
    assert len(intake.file_sha256) == 64
    assert not container.intakes.pendencies_for(result.protocol)


def test_agent_asks_for_what_is_missing_then_completes(
    container: Container, make_input: MakeInput
) -> None:
    first = container.reception.start(make_input("atestado_escaneado.pdf"))
    assert first.status is CaseStatus.AWAITING_EMPLOYEE
    assert first.missing == ["tipo_documento", "matricula", "data_inicio"]
    assert "matrícula" in first.message

    reply = make_input(
        declared_type=DocumentType.MEDICAL_CERTIFICATE, employee_id="1001", absence_start=YESTERDAY
    )
    final = container.reception.reply(first.session_id, reply)
    assert final.status is CaseStatus.RECEIVED
    intake = container.intakes.get(final.protocol)
    assert intake.document_type is DocumentType.MEDICAL_CERTIFICATE
    assert intake.attempts == 2
    assert _actions(container, first.session_id) == [
        "avaliacao_do_dossie",
        "pedido_ao_colaborador",
        "avaliacao_do_dossie",
    ]


@pytest.mark.parametrize(
    ("bad_sample", "missing"),
    [
        ("atestado_foto_desfocada.png", "legibilidade"),
        ("receita_medica.pdf", "tipo_nao_aceito"),
        ("anotacao.txt", "formato_do_arquivo"),
    ],
)
def test_bad_file_is_replaced_by_resubmission(
    container: Container, make_input: MakeInput, bad_sample: str, missing: str
) -> None:
    info = {
        "employee_id": "1001",
        "absence_start": YESTERDAY,
        "declared_type": DocumentType.MEDICAL_CERTIFICATE,
    }
    first = container.reception.start(make_input(bad_sample, **info))
    assert first.status is CaseStatus.AWAITING_EMPLOYEE
    assert first.missing == [missing]

    final = container.reception.reply(first.session_id, make_input("atestado_medico.pdf"))
    assert final.status is CaseStatus.RECEIVED
    staging = container.settings.files_dir / "staging"
    assert list(staging.iterdir()) == []


def test_late_delivery_opens_pendency_for_hr(container: Container, make_input: MakeInput) -> None:
    data = make_input("atestado_medico.pdf", employee_id="1001", absence_start=date(2026, 10, 1))
    result = container.reception.start(data)

    assert result.status is CaseStatus.RECEIVED
    assert "prazo" in result.message
    [pendency] = container.intakes.pendencies_for(result.protocol)
    assert (pendency.kind, pendency.target_area, pendency.rule_id) == (
        "entrega_fora_do_prazo",
        "RH",
        "R03",
    )
    [entry] = container.audit.list_for(result.protocol)
    assert entry.rule_ids == ["R03"]


def test_hand_over_to_hr_after_max_attempts(container: Container, make_input: MakeInput) -> None:
    result = container.reception.start(make_input("imagem_em_branco.png"))
    limit = container.rules.reception.max_resubmission_attempts
    for _ in range(limit):
        assert result.status is CaseStatus.AWAITING_EMPLOYEE
        result = container.reception.reply(result.session_id, make_input())

    assert result.status is CaseStatus.PENDING_HR
    intake = container.intakes.get(result.protocol)
    assert intake.attempts == limit + 1
    [pendency] = container.intakes.pendencies_for(result.protocol)
    assert pendency.kind == "envio_incompleto"


def test_paused_session_survives_restart(settings: Settings, make_input: MakeInput) -> None:
    first_app = build_container(settings, clock=fixed_clock(NOW))
    paused = first_app.reception.start(make_input("atestado_medico.pdf"))

    restarted = build_container(settings, clock=fixed_clock(NOW))
    reply = make_input(employee_id="1001", absence_start=YESTERDAY)
    final = restarted.reception.reply(paused.session_id, reply)
    assert final.status is CaseStatus.RECEIVED


def test_reply_to_unknown_or_finished_session(container: Container, make_input: MakeInput) -> None:
    with pytest.raises(NotFoundError):
        container.reception.reply("nao-existe", make_input())
    done = container.reception.start(
        make_input("atestado_medico.pdf", employee_id="1001", absence_start=YESTERDAY)
    )
    with pytest.raises(SessionStateError):
        container.reception.reply(done.session_id, make_input())


def test_checkpoint_does_not_store_document_text(
    container: Container, make_input: MakeInput
) -> None:
    container.reception.start(make_input("atestado_medico.pdf"))
    raw = container.settings.checkpoint_path.read_bytes()
    assert b"afastamento de suas atividades" not in raw
