"""Testes da percepção do Agente 2: leitura do texto, extração, ancoragem e R09."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from sinergia.agents.processing.extraction import (
    LlmExtraction,
    LlmExtractor,
    RegexExtractor,
    build_extraction,
)
from sinergia.agents.processing.grounding import grounded_fields, prepare_text
from sinergia.agents.processing.models import ExtractedFields
from sinergia.agents.processing.ocr import EasyOcrEngine, group_lines
from sinergia.agents.processing.text_reader import DocumentTextReader
from sinergia.core.domain import DocumentType

TEXT = (
    "ATESTADO MÉDICO\nPaciente: Joana Exemplo da Silva\n"
    "Atesto que a paciente acima necessita de 3\ndias de afastamento a partir de 27/10/2026.\n"
    "Campinas, 27/10/2026\nDra. Helena Ficticia Ramos — CRM 900123/SP\n"
    "Assinatura e carimbo do médico"
)


class StubModel:
    """LLM falso com saída estruturada: devolve uma resposta fixa ou falha."""

    def __init__(self, answer: LlmExtraction | None = None) -> None:
        self._answer = answer

    def with_structured_output(self, _: Any) -> "StubModel":
        return self

    def invoke(self, _: Any) -> LlmExtraction:
        if self._answer is None:
            raise RuntimeError("provedor fora do ar")
        return self._answer


def _extract(extractor: Any, text: str = TEXT, ocr: float | None = None):
    return build_extraction(extractor, text, "1001", DocumentType.MEDICAL_CERTIFICATE, ocr)


def test_regex_extracts_every_field() -> None:
    extraction = _extract(RegexExtractor())
    fields = extraction.fields
    assert fields.employee_name == "Joana Exemplo da Silva"
    assert (fields.start_date, fields.days, fields.issue_date) == (
        date(2026, 10, 27),
        3,
        date(2026, 10, 27),
    )
    assert (fields.crm_number, fields.crm_uf, fields.signed) == ("900123", "SP", True)
    assert fields.end_date == date(2026, 10, 29)
    assert extraction.derived == ["end_date"]
    assert min(extraction.confidence.values()) >= 0.8


def test_ocr_noise_is_normalized() -> None:
    prepared = prepare_text("Atesto que necessita de3 dias a partir de 27/1O/2026 CRM 9oo123/SP")
    assert "de3 dias" in prepared
    assert "27/10/2026" in prepared
    assert "900123/sp" in prepared


@pytest.mark.parametrize("sample", ["atestado_foto.png", "atestado_escaneado.pdf"])
def test_ocr_path_extracts_from_images(samples: Path, ocr: EasyOcrEngine, sample: str) -> None:
    mime = "image/png" if sample.endswith("png") else "application/pdf"
    read = DocumentTextReader(ocr).read(samples / sample, mime)
    assert read.source == "ocr"
    extraction = _extract(RegexExtractor(), read.text, read.ocr_confidence)
    assert extraction.fields.crm_number == "900123"
    assert extraction.fields.days == 3


def test_pdf_text_layer_skips_ocr(samples: Path) -> None:
    class NoOcr:
        def read(self, _: Any) -> list[tuple[str, float]]:
            raise AssertionError("não deveria usar OCR")

    read = DocumentTextReader(NoOcr()).read(samples / "atestado_medico.pdf", "application/pdf")
    assert read.source == "pdf_texto"


def test_llm_values_are_grounded_and_hallucinated_cid_is_dropped() -> None:
    answer = LlmExtraction(
        employee_name="Maria Inventada",
        start_date="27/10/2026",
        days=3,
        crm_number="900123",
        crm_uf="SP",
        cid="F32",
    )
    extraction = _extract(LlmExtractor(StubModel(answer), RegexExtractor()))
    assert extraction.method == "llm"
    assert extraction.fields.cid is None
    assert extraction.cid_discarded
    assert extraction.confidence["employee_name"] < 0.8
    assert extraction.fields.doctor_name == "Dra. Helena Ficticia Ramos"


def test_llm_failure_falls_back_to_rules() -> None:
    extraction = _extract(LlmExtractor(StubModel(None), RegexExtractor()))
    assert extraction.method == "regras"
    assert extraction.fields.crm_number == "900123"


def test_cid_kept_only_when_written_in_document() -> None:
    with_cid = TEXT + "\nCID: J11 (informado com autorização da paciente)"
    assert _extract(RegexExtractor(), with_cid).fields.cid == "J11"
    assert _extract(RegexExtractor()).fields.cid is None


def test_fields_accept_brazilian_dates_and_clean_crm() -> None:
    fields = ExtractedFields(start_date="27/10/2026", crm_number="CRM 900.123", crm_uf="sp")
    assert fields.start_date == date(2026, 10, 27)
    assert (fields.crm_number, fields.crm_uf) == ("900123", "SP")


OCR_ACCENTS = (
    "ATESTADOMDICO\nPaciente: Mrcia Conceio Antnio\nAtesto que a paciente acima necessita de 2\n"
    "dias de afastamento a partir de 27/10/2026.\nSoJos dos Campos, 27/10/2026\n"
    "Dr. Joo Fictcio Arajo  CRM 900456/SP\nAssinatura e carimbo do mdico"
)


@pytest.mark.parametrize(
    ("name", "grounded"),
    [
        ("Márcia Conceição Antônio", True),
        ("Mrcia Conceio Antnio", True),
        ("Márcia Constância Antônio", False),
    ],
)
def test_names_survive_accents_dropped_by_ocr(name: str, grounded: bool) -> None:
    fields = ExtractedFields(employee_name=name)
    assert grounded_fields(fields, prepare_text(OCR_ACCENTS))["employee_name"] is grounded


def test_llm_may_restore_accents_but_not_change_letters() -> None:
    answer = LlmExtraction(
        employee_name="Márcia Conceição Antônio",
        doctor_name="Dr. João Fictício Araújo",
        start_date="27/10/2026",
        days=2,
    )
    extraction = _extract(LlmExtractor(StubModel(answer), RegexExtractor()), OCR_ACCENTS, 0.97)
    assert extraction.fields.employee_name == "Márcia Conceição Antônio"
    assert extraction.confidence["employee_name"] >= 0.8
    assert extraction.confidence["doctor_name"] >= 0.8


def test_accented_photo_is_read_end_to_end(samples: Path, ocr: EasyOcrEngine) -> None:
    read = DocumentTextReader(ocr).read(samples / "atestado_foto_acentos.png", "image/png")
    extraction = _extract(RegexExtractor(), read.text, read.ocr_confidence)
    assert extraction.fields.employee_name == "Márcia Conceição Antônio"
    assert extraction.fields.doctor_name == "Dr. João Fictício Araújo"
    assert extraction.fields.crm_number == "900456"
    assert min(extraction.confidence.values()) >= 0.8
    assert read.ocr_confidence >= 0.6


def _piece(x: float, y: float, text: str, conf: float = 0.9) -> list:
    """Trecho no formato do EasyOCR: cantos, texto e confiança."""
    return [[[x, y], [x + 100, y], [x + 100, y + 30], [x, y + 30]], text, conf]


def test_lines_are_rebuilt_in_reading_order_even_when_tilted() -> None:
    pieces = [
        _piece(400, 128, "CRM 900456/SP"),
        _piece(10, 60, "Paciente:"),
        _piece(10, 120, "Dr. João"),
        _piece(200, 64, "Márcia"),
        _piece(210, 124, "Araújo"),
        _piece(10, 10, "ATESTADO MÉDICO"),
    ]
    assert [text for text, _ in group_lines(pieces)] == [
        "ATESTADO MÉDICO",
        "Paciente: Márcia",
        "Dr. João Araújo CRM 900456/SP",
    ]
