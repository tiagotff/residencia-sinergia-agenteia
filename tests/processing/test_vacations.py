"""Testes das férias: cadastro, importação de CSV e a R07 cruzando com férias."""

from datetime import date
from pathlib import Path

import pytest

from sinergia.agents.processing.models import CrmCheck, CrmStatus, ExtractedFields, Extraction
from sinergia.agents.processing.validation import validate_absence
from sinergia.bootstrap import Container
from sinergia.core.domain import AbsenceStatus, DocumentType
from sinergia.core.rules import RuleCatalog
from sinergia.data.vacations import Vacation, read_vacations_csv
from tests.conftest import NOW, YESTERDAY

REGULAR = CrmCheck(status=CrmStatus.REGULAR, detail="ok", source="teste")


def _extraction(start: date, end: date) -> Extraction:
    fields = ExtractedFields(
        employee_name="Joana Exemplo da Silva",
        start_date=start,
        end_date=end,
        days=(end - start).days + 1,
        doctor_name="Dra. Helena",
        crm_number="900123",
        crm_uf="SP",
        signed=True,
    )
    return Extraction(
        employee_id="7007",
        document_type=DocumentType.MEDICAL_CERTIFICATE,
        fields=fields,
        confidence={},
        method="regras",
    )


def test_r07_with_vacations(rules: RuleCatalog) -> None:
    vacation = Vacation(employee_id="7007", start_date="26/10/2026", end_date="09/11/2026")
    inside = _extraction(date(2026, 10, 27), date(2026, 10, 29))
    validation = validate_absence(inside, REGULAR, [], rules.processing, vacations=[vacation])
    assert validation.rule_ids == ["R07"]
    assert "férias de 26/10/2026 a 09/11/2026" in validation.violations[0].message
    after = _extraction(date(2026, 11, 10), date(2026, 11, 12))
    assert validate_absence(after, REGULAR, [], rules.processing, vacations=[vacation]).valid


def test_vacation_end_before_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="anterior ao início"):
        Vacation(employee_id="1", start_date="10/11/2026", end_date="01/11/2026")


def test_repository_ignores_duplicates(container: Container) -> None:
    vacation = Vacation(employee_id="7007", start_date="2026-10-26", end_date="2026-11-09")
    assert container.vacations.add(vacation, NOW) is True
    assert container.vacations.add(vacation, NOW) is False
    assert container.vacations.for_employee("7007") == [vacation]


def test_csv_import_semicolon_and_comma(container: Container, samples: Path, tmp_path) -> None:
    assert container.vacations.import_csv(samples / "ferias.csv", NOW) == 2
    comma = tmp_path / "ferias.csv"
    comma.write_text("employee_id,start_date,end_date\n9009,2026-12-01,2026-12-20\n")
    assert container.vacations.import_csv(comma, NOW) == 1


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("matricula;inicio;fim\n1;01/12/2026;10/12/2026\n", "Colunas ausentes"),
        ("employee_id;start_date;end_date\n1;01/12/2026;xx\n", "Linha 2"),
    ],
)
def test_invalid_csv(tmp_path: Path, content: str, message: str) -> None:
    path = tmp_path / "ferias.csv"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        read_vacations_csv(path)


def test_certificate_during_vacation_goes_to_review(
    container: Container, samples: Path, make_input
) -> None:
    container.vacations.import_csv(samples / "ferias.csv", NOW)
    data = make_input("atestado_medico.pdf", employee_id="7007", absence_start=YESTERDAY)
    protocol = container.reception.start(data).protocol
    absence = container.absences.get(protocol)
    assert (absence.status, absence.violated_rules) == (AbsenceStatus.HUMAN_REVIEW, ["R07"])
