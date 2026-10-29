"""Inspeção técnica do arquivo recebido: formato, tamanho e legibilidade mínima (R02).

O formato é identificado pelo conteúdo (assinatura do arquivo), não pela extensão.
"""

import io
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from sinergia.agents.reception.models import FileIssue, FileReport
from sinergia.core.rules import ReceptionRules

_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
_ANALYSIS_WIDTH = 1000


def sniff_mime(content: bytes) -> str | None:
    """Identifica o tipo do arquivo pela assinatura dos primeiros bytes."""
    for signature, mime in _SIGNATURES:
        if content.startswith(signature):
            return mime
    return None


class ContentInspector(Protocol):
    """Estratégia de inspeção para um tipo de arquivo."""

    def inspect(self, content: bytes) -> tuple[list[FileIssue], int | None, str]:
        """Devolve problemas, número de páginas e texto extraído."""
        ...


class PdfInspector:
    """Confere se o PDF abre, não tem senha e respeita o limite de páginas."""

    def __init__(self, rules: ReceptionRules) -> None:
        self._rules = rules

    def inspect(self, content: bytes) -> tuple[list[FileIssue], int | None, str]:
        """Inspeciona um PDF e extrai a camada de texto, se existir."""
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                return [FileIssue.PASSWORD_PROTECTED], None, ""
            pages = len(reader.pages)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except (PdfReadError, ValueError, OSError):
            return [FileIssue.CORRUPTED], None, ""
        issues = [FileIssue.TOO_MANY_PAGES] if pages > self._rules.max_pdf_pages else []
        if pages == 0:
            issues.append(FileIssue.EMPTY)
        return issues, pages, text


class ImageInspector:
    """Confere resolução, contraste (imagem em branco) e nitidez de uma foto."""

    def __init__(self, rules: ReceptionRules) -> None:
        self._rules = rules

    def inspect(self, content: bytes) -> tuple[list[FileIssue], int | None, str]:
        """Inspeciona uma imagem; o texto fica a cargo do OCR do Agente 2."""
        try:
            image = Image.open(io.BytesIO(content))
            image.load()
        except (UnidentifiedImageError, OSError):
            return [FileIssue.CORRUPTED], None, ""
        return self._quality_issues(image), 1, ""

    def _quality_issues(self, image: Image.Image) -> list[FileIssue]:
        """Aplica os limiares de qualidade da regra R02."""
        if image.width < self._rules.min_image_width_px or (
            image.height < self._rules.min_image_height_px
        ):
            return [FileIssue.LOW_RESOLUTION]
        gray = _normalized_gray(image)
        if ImageStat.Stat(gray).stddev[0] < self._rules.min_image_contrast:
            return [FileIssue.BLANK]
        edges = gray.filter(ImageFilter.FIND_EDGES)
        inner = edges.crop((2, 2, edges.width - 2, edges.height - 2))  # sem a moldura do filtro
        if ImageStat.Stat(inner).stddev[0] < self._rules.min_image_sharpness:
            return [FileIssue.BLURRY]
        return []


def _normalized_gray(image: Image.Image) -> Image.Image:
    """Converte para tons de cinza numa largura fixa, para comparar fotos de tamanhos diferentes."""
    gray = image.convert("L")
    height = max(1, round(gray.height * _ANALYSIS_WIDTH / gray.width))
    return gray.resize((_ANALYSIS_WIDTH, height))


class FileInspector:
    """Escolhe a estratégia de inspeção pelo tipo do arquivo e aplica as regras gerais."""

    def __init__(self, rules: ReceptionRules) -> None:
        self._rules = rules
        image = ImageInspector(rules)
        self._by_mime: dict[str, ContentInspector] = {
            "application/pdf": PdfInspector(rules),
            "image/jpeg": image,
            "image/png": image,
        }

    def inspect(self, path: str | None) -> FileReport:
        """Gera o laudo técnico do arquivo no caminho informado."""
        if path is None or not Path(path).exists():
            return FileReport(present=False, issues=[FileIssue.MISSING])
        content = Path(path).read_bytes()
        mime = sniff_mime(content)
        report = FileReport(present=True, mime=mime, size_bytes=len(content))
        general = self._general_issues(content, mime)
        if general:
            return report.model_copy(update={"issues": general})
        issues, pages, text = self._by_mime[mime].inspect(content)
        return report.model_copy(update={"issues": issues, "pages": pages, "text": text})

    def _general_issues(self, content: bytes, mime: str | None) -> list[FileIssue]:
        """Problemas que dispensam abrir o arquivo: vazio, formato e tamanho."""
        if not content:
            return [FileIssue.EMPTY]
        if mime is None or mime not in self._rules.accepted_mime_types:
            return [FileIssue.UNSUPPORTED_FORMAT]
        if len(content) > self._rules.max_file_size_bytes:
            return [FileIssue.TOO_LARGE]
        return []
