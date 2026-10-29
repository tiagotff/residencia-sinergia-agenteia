"""Testes das regras do Agente 2: R04–R08 e prazos legais R10/R11."""

from datetime import date, datetime

import pytest

from sinergia.agents.processing.deadlines import legal_escalations
from sinergia.agents.processing.models import (
    CrmCheck,
    CrmStatus,
    ExtractedFields,
    Extraction,
)
from sinergia.agents.processing.validation import validate_absence
from sinergia.core.domain import AbsenceStatus, DocumentType
from sinergia.core.rules import ProcessingRules, RuleCatalog
from sinergia.data.absences import Absence

REGULAR = CrmCheck(status=CrmStatus.REGULAR, detail="Situação: Regular.", source="teste")
UNVERIFIED = CrmCheck(status=CrmStatus.NOT_VERIFIED, detail="Não verificado.", source="teste")


@pytest.fixture
def processing(rules: RuleCatalog) -> ProcessingRules:
    return rules.processing


def _extraction(**changes: object) -> Extraction:
    fields = ExtractedFields(
        employee_name="Joana Exemplo da Silva",
        issue_date=date(2026, 10, 27),
        start_date=date(2026, 10, 27),
        end_date=date(2026, 10, 29),
        days=3,
        doctor_name="Dra. Helena Ficticia Ramos",
        crm_number="900123",
        crm_uf="SP",
        signed=True,
    ).model_copy(update=changes)
    confidence = dict.fromkeys(fields.model_dump(exclude_none=True), 0.9)
    return Extraction(
        employee_id="1001",
        document_type=DocumentType.MEDICAL_CERTIFICATE,
        fields=fields,
        confidence=confidence,
        method="regras",
    )


def _absence(protocol: str, start: date, days: int, cid: str | None = None) -> Absence:
    return Absence(
        protocol=protocol,
        session_id="s",
        employee_id="1001",
        start_date=start,
        end_date=date.fromordinal(start.toordinal() + days - 1),
        days=days,
        cid=cid,
        status=AbsenceStatus.VALID,
        extraction_method="regras",
        rules_version="t",
        updated_at=datetime(2026, 10, 28),
    )


def _rules(extraction: Extraction, processing: ProcessingRules, **kwargs: object) -> list[str]:
    crm = kwargs.pop("crm", REGULAR)
    others = kwargs.pop("others", [])
    return validate_absence(extraction, crm, others, processing, **kwargs).rule_ids


def test_valid_certificate(processing: ProcessingRules) -> None:
    assert _rules(_extraction(), processing) == []


def test_r04_missing_signature_and_crm(processing: ProcessingRules) -> None:
    validation = validate_absence(
        _extraction(signed=None, crm_number=None), REGULAR, [], processing
    )
    assert validation.rule_ids == ["R04"]
    assert validation.status is AbsenceStatus.PENDING
    assert validation.violations[0].fields == ["crm_number", "signed"]


def test_r04_attendance_statement_needs_no_days(processing: ProcessingRules) -> None:
    extraction = _extraction(days=None, end_date=None).model_copy(
        update={"document_type": DocumentType.ATTENDANCE_STATEMENT}
    )
    assert _rules(extraction, processing) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"end_date": date(2026, 10, 20)},
        {"issue_date": date(2026, 11, 5)},
        {"days": 5},
    ],
)
def test_r05_incoherent_dates(processing: ProcessingRules, changes: dict) -> None:
    assert _rules(_extraction(**changes), processing) == ["R05"]


def test_r05_issue_within_tolerance(processing: ProcessingRules) -> None:
    assert _rules(_extraction(issue_date=date(2026, 10, 28)), processing) == []


def test_r06_unverified_crm_goes_to_review(processing: ProcessingRules) -> None:
    validation = validate_absence(_extraction(), UNVERIFIED, [], processing)
    assert validation.rule_ids == ["R06"]
    assert validation.status is AbsenceStatus.HUMAN_REVIEW


def test_r07_overlap(processing: ProcessingRules) -> None:
    others = [_absence("SNG-X", date(2026, 10, 29), 2)]
    assert _rules(_extraction(), processing, others=others) == ["R07"]
    distant = [_absence("SNG-Y", date(2026, 10, 1), 2)]
    assert _rules(_extraction(), processing, others=distant) == []


def test_r08_low_confidence(processing: ProcessingRules) -> None:
    extraction = _extraction()
    extraction.confidence["doctor_name"] = 0.3
    validation = validate_absence(extraction, REGULAR, [], processing)
    assert validation.rule_ids == ["R08"]
    assert validation.violations[0].fields == ["doctor_name"]


def test_r08_low_ocr_reading(processing: ProcessingRules) -> None:
    extraction = _extraction().model_copy(update={"ocr_confidence": 0.4})
    validation = validate_absence(extraction, REGULAR, [], processing)
    assert validation.rule_ids == ["R08"]
    assert "0.40" in validation.violations[0].message
    good = _extraction().model_copy(update={"ocr_confidence": 0.85})
    assert validate_absence(good, REGULAR, [], processing).valid


def test_human_approval_replaces_r06_and_r08_but_not_r04(processing: ProcessingRules) -> None:
    extraction = _extraction()
    extraction.confidence["doctor_name"] = 0.3
    assert _rules(extraction, processing, crm=UNVERIFIED, human_approved=True) == []
    missing = _extraction(signed=None)
    assert _rules(missing, processing, human_approved=True) == ["R04"]


def test_r10_more_than_15_days(processing: ProcessingRules) -> None:
    [escalation] = legal_escalations(_absence("SNG-A", date(2026, 10, 27), 20), [], processing)
    assert (escalation.rule_id, escalation.kind) == ("R10", "encaminhamento_inss")


def test_15_days_is_not_r10(processing: ProcessingRules) -> None:
    assert legal_escalations(_absence("SNG-A", date(2026, 10, 27), 15), [], processing) == []


def test_r11_same_cause_within_60_days(processing: ProcessingRules) -> None:
    previous = [_absence("SNG-A", date(2026, 10, 1), 10, cid="J11")]
    current = _absence("SNG-B", date(2026, 10, 27), 8, cid="J11.1")
    [escalation] = legal_escalations(current, previous, processing)
    assert escalation.rule_id == "R11"
    other_cause = _absence("SNG-C", date(2026, 10, 27), 8, cid="M54")
    assert legal_escalations(other_cause, previous, processing) == []
    too_old = [_absence("SNG-D", date(2026, 6, 1), 10, cid="J11")]
    assert legal_escalations(current, too_old, processing) == []
