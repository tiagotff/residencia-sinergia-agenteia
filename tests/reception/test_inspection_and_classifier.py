"""Testes da percepção do Agente 1: inspeção do arquivo (R02) e classificação (R01)."""

from pathlib import Path

import pytest

from sinergia.agents.reception.classifier import classify_document
from sinergia.agents.reception.inspection import FileInspector, sniff_mime
from sinergia.agents.reception.models import FileIssue
from sinergia.core.domain import DocumentType
from sinergia.core.rules import RuleCatalog


@pytest.fixture
def inspector(rules: RuleCatalog) -> FileInspector:
    return FileInspector(rules.reception)


@pytest.mark.parametrize(
    ("sample", "issues"),
    [
        ("atestado_medico.pdf", []),
        ("atestado_escaneado.pdf", []),
        ("atestado_foto.png", []),
        ("atestado_foto_desfocada.png", [FileIssue.BLURRY]),
        ("atestado_foto_pequena.png", [FileIssue.LOW_RESOLUTION]),
        ("imagem_em_branco.png", [FileIssue.BLANK]),
        ("pdf_corrompido.pdf", [FileIssue.CORRUPTED]),
        ("anotacao.txt", [FileIssue.UNSUPPORTED_FORMAT]),
    ],
)
def test_inspection_flags_quality_issues(
    inspector: FileInspector, samples: Path, sample: str, issues: list[FileIssue]
) -> None:
    assert inspector.inspect(str(samples / sample)).issues == issues


def test_missing_file(inspector: FileInspector) -> None:
    report = inspector.inspect(None)
    assert not report.present
    assert report.issues == [FileIssue.MISSING]


def test_empty_and_too_large_files(inspector: FileInspector, tmp_path: Path) -> None:
    empty = tmp_path / "vazio.pdf"
    empty.write_bytes(b"")
    big = tmp_path / "grande.pdf"
    big.write_bytes(b"%PDF-" + b"0" * (11 * 1024 * 1024))
    assert inspector.inspect(str(empty)).issues == [FileIssue.EMPTY]
    assert inspector.inspect(str(big)).issues == [FileIssue.TOO_LARGE]


def test_mime_is_read_from_content_not_extension(samples: Path, tmp_path: Path) -> None:
    disguised = tmp_path / "foto.pdf"
    disguised.write_bytes((samples / "atestado_foto.png").read_bytes())
    assert sniff_mime(disguised.read_bytes()) == "image/png"


def test_extracted_text_never_serialized(inspector: FileInspector, samples: Path) -> None:
    report = inspector.inspect(str(samples / "atestado_medico.pdf"))
    assert "afastamento" in report.text.lower()
    assert "text" not in report.model_dump()


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        ("atestado_medico.pdf", DocumentType.MEDICAL_CERTIFICATE),
        ("declaracao_comparecimento.pdf", DocumentType.ATTENDANCE_STATEMENT),
        ("atestado_acompanhante.pdf", DocumentType.COMPANION_CERTIFICATE),
        ("receita_medica.pdf", DocumentType.OTHER),
        ("atestado_escaneado.pdf", DocumentType.UNKNOWN),
    ],
)
def test_classifier_reads_document_type(
    inspector: FileInspector, samples: Path, sample: str, expected: DocumentType
) -> None:
    text = inspector.inspect(str(samples / sample)).text
    assert classify_document(text) is expected


def test_classifier_ignores_accents_and_case() -> None:
    assert classify_document("DECLARAÇÃO: ESTEVE PRESENTE") is DocumentType.ATTENDANCE_STATEMENT
