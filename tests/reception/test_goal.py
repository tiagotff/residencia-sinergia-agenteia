"""Testes da decisão do Agente 1: o dossiê atinge o objetivo? (R01–R03)."""

from datetime import date

from sinergia.agents.reception.goal import evaluate_dossier, resolve_document_type
from sinergia.agents.reception.models import FileIssue, FileReport, MissingItem, Submission
from sinergia.core.domain import DocumentType
from sinergia.core.rules import RuleCatalog

TODAY = date(2026, 10, 28)
GOOD_FILE = FileReport(present=True, mime="application/pdf", size_bytes=100, pages=1)


def _complete(**changes: object) -> Submission:
    base = Submission(employee_id="1001", absence_start=date(2026, 10, 27), file_path="x.pdf")
    return base.model_copy(update=changes)


def test_complete_dossier_meets_goal(rules: RuleCatalog) -> None:
    assessment = evaluate_dossier(
        _complete(), GOOD_FILE, DocumentType.MEDICAL_CERTIFICATE, rules.reception, TODAY
    )
    assert assessment.complete
    assert assessment.rule_hits == []
    assert assessment.days_since_start == 1


def test_everything_missing(rules: RuleCatalog) -> None:
    no_file = FileReport(present=False, issues=[FileIssue.MISSING])
    assessment = evaluate_dossier(
        Submission(), no_file, DocumentType.UNKNOWN, rules.reception, TODAY
    )
    assert assessment.missing == [
        MissingItem.FILE,
        MissingItem.DOCUMENT_TYPE,
        MissingItem.EMPLOYEE_ID,
        MissingItem.ABSENCE_START,
    ]
    assert assessment.rule_hits == ["R01", "R02"]


def test_unreadable_and_format_issues_map_to_r02(rules: RuleCatalog) -> None:
    blurry = GOOD_FILE.model_copy(update={"issues": [FileIssue.BLURRY]})
    pages = GOOD_FILE.model_copy(update={"issues": [FileIssue.TOO_MANY_PAGES]})
    args = (DocumentType.MEDICAL_CERTIFICATE, rules.reception, TODAY)
    assert evaluate_dossier(_complete(), blurry, *args).missing == [MissingItem.FILE_UNREADABLE]
    assert evaluate_dossier(_complete(), pages, *args).missing == [MissingItem.FILE_FORMAT]


def test_document_not_in_accepted_list(rules: RuleCatalog) -> None:
    assessment = evaluate_dossier(
        _complete(), GOOD_FILE, DocumentType.OTHER, rules.reception, TODAY
    )
    assert assessment.missing == [MissingItem.DOCUMENT_TYPE_NOT_ACCEPTED]


def test_detected_type_wins_over_declared() -> None:
    declared = DocumentType.COMPANION_CERTIFICATE
    assert resolve_document_type(declared, DocumentType.MEDICAL_CERTIFICATE) is (
        DocumentType.MEDICAL_CERTIFICATE
    )
    assert resolve_document_type(declared, DocumentType.UNKNOWN) is declared


def test_late_delivery_flags_r03_without_blocking(rules: RuleCatalog) -> None:
    late = _complete(absence_start=date(2026, 10, 20))
    assessment = evaluate_dossier(
        late, GOOD_FILE, DocumentType.MEDICAL_CERTIFICATE, rules.reception, TODAY
    )
    assert assessment.complete
    assert assessment.late_delivery
    assert assessment.rule_hits == ["R03"]


def test_delivery_on_deadline_is_not_late(rules: RuleCatalog) -> None:
    on_time = _complete(absence_start=date(2026, 10, 26))
    assessment = evaluate_dossier(
        on_time, GOOD_FILE, DocumentType.MEDICAL_CERTIFICATE, rules.reception, TODAY
    )
    assert not assessment.late_delivery


def test_merge_keeps_previous_answers() -> None:
    first = Submission(employee_id="1001", file_path="a.pdf")
    reply = Submission(absence_start=date(2026, 10, 27))
    merged = first.merge(reply)
    assert merged.employee_id == "1001"
    assert merged.file_path == "a.pdf"
    assert merged.absence_start == date(2026, 10, 27)
