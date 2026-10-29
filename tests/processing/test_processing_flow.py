"""Testes ponta a ponta: Agente 1 recebe, Agente 2 registra ou pede revisão humana."""

from collections.abc import Callable

import pytest

from sinergia.agents.processing.models import ReviewDecision
from sinergia.agents.reception.service import ReceptionInput
from sinergia.bootstrap import Container, Overrides, build_container
from sinergia.core.clock import fixed_clock
from sinergia.core.domain import AbsenceStatus, CaseStatus, DocumentType
from sinergia.core.errors import SessionStateError
from sinergia.core.settings import Settings
from tests.conftest import NOW, YESTERDAY

MakeInput = Callable[..., ReceptionInput]


@pytest.fixture
def submit(container: Container, make_input: MakeInput) -> Callable[..., str]:
    """Envia uma amostra completa e devolve o protocolo."""

    def _submit(sample: str, employee_id: str = "1001", start=YESTERDAY, **extra: object) -> str:
        if sample.endswith(".png"):
            extra.setdefault("declared_type", DocumentType.MEDICAL_CERTIFICATE)
        data = make_input(sample, employee_id=employee_id, absence_start=start, **extra)
        result = container.reception.start(data)
        assert result.status is CaseStatus.RECEIVED
        return result.protocol

    return _submit


def _decide(container: Container, protocol: str, decision: str = "aprovar", **corrections):
    return container.review.decide(
        protocol, ReviewDecision(decision=decision, reviewer="Ana (RH)", corrections=corrections)
    )


@pytest.mark.parametrize(
    "sample",
    [
        "atestado_medico.pdf",
        "atestado_foto.png",
        "declaracao_comparecimento.pdf",
        "atestado_acompanhante.pdf",
    ],
)
def test_valid_documents_are_registered(container: Container, submit, sample: str) -> None:
    protocol = submit(sample)
    absence = container.absences.get(protocol)
    assert absence.status is AbsenceStatus.VALID
    assert absence.crm_status == "regular"
    assert absence.employee_name.lower() == "joana exemplo da silva"
    actions = [entry.action for entry in container.audit.list_for(protocol)]
    assert actions[1:] == ["extracao", "validacao", "afastamento_registrado"]


def test_r10_long_absence_is_escalated(container: Container, submit) -> None:
    protocol = submit("atestado_longo_cid.pdf")
    assert container.absences.get(protocol).status is AbsenceStatus.VALID
    rules = {p.rule_id for p in container.intakes.pendencies_for(protocol)}
    assert rules == {"R10"}


def test_r11_same_cause_sum(container: Container, submit) -> None:
    from datetime import date

    submit("atestado_cid_outubro.pdf", start=date(2026, 10, 1))
    protocol = submit("atestado_cid_novembro.pdf")
    rules = {p.rule_id for p in container.intakes.pendencies_for(protocol)}
    assert rules == {"R11"}


def test_review_with_correction_validates_and_records_feedback(
    container: Container, submit
) -> None:
    protocol = submit("atestado_datas_incoerentes.pdf")
    assert container.absences.get(protocol).violated_rules == ["R05"]
    [case] = container.review.pending()
    assert case.protocol == protocol

    absence = _decide(container, protocol, issue_date="27/10/2026")
    assert absence.status is AbsenceStatus.VALID
    assert absence.reviewed_by == "Ana (RH)"
    assert container.absences.feedback_count(protocol) == 1
    assert container.review.pending() == []


def test_human_can_vouch_for_crm(container: Container, submit) -> None:
    protocol = submit("atestado_crm_aposentado.pdf")
    absence = container.absences.get(protocol)
    assert (absence.status, absence.violated_rules) == (AbsenceStatus.HUMAN_REVIEW, ["R06"])
    assert _decide(container, protocol).status is AbsenceStatus.VALID


def test_missing_fields_stay_pending_until_corrected(container: Container, submit) -> None:
    protocol = submit("atestado_sem_assinatura.pdf")
    assert container.absences.get(protocol).status is AbsenceStatus.PENDING
    assert _decide(container, protocol).status is AbsenceStatus.PENDING
    absence = _decide(container, protocol, crm_number="900123", crm_uf="SP", signed="sim")
    assert absence.status is AbsenceStatus.VALID


def test_invalidation_and_overlap(container: Container, submit) -> None:
    first = submit("atestado_medico.pdf")
    second = submit("atestado_foto.png")
    assert container.absences.get(second).violated_rules == ["R07"]
    assert _decide(container, second, "invalidar").status is AbsenceStatus.INVALIDATED
    assert container.absences.get(first).status is AbsenceStatus.VALID


def test_invalid_correction_keeps_case_waiting(container: Container, submit) -> None:
    protocol = submit("atestado_datas_incoerentes.pdf")
    with pytest.raises(ValueError, match="Correção inválida"):
        _decide(container, protocol, days="muitos")
    assert container.review.get(protocol).protocol == protocol


def test_review_payload_hides_cid(settings: Settings, make_input: MakeInput) -> None:
    unverified = settings.model_copy(update={"crm_verifier": "none"})
    container = build_container(unverified, Overrides(clock=fixed_clock(NOW)))
    data = make_input("atestado_cid_novembro.pdf", employee_id="1001", absence_start=YESTERDAY)
    protocol = container.reception.start(data).protocol
    case = container.review.get(protocol)
    assert case.payload["cid_present"] is True
    assert "cid" not in case.payload["fields"]
    assert "J11" not in str(case.payload)


def test_decision_requires_waiting_case(container: Container, submit) -> None:
    protocol = submit("atestado_medico.pdf")
    with pytest.raises(SessionStateError):
        _decide(container, protocol)


def test_employee_cannot_answer_review_pause(container: Container, make_input: MakeInput) -> None:
    data = make_input(
        "atestado_crm_aposentado.pdf",
        employee_id="1001",
        absence_start=YESTERDAY,
        declared_type=DocumentType.MEDICAL_CERTIFICATE,
    )
    result = container.reception.start(data)
    with pytest.raises(SessionStateError):
        container.reception.reply(result.session_id, make_input())
