"""Leitura do texto do documento: camada de texto do PDF ou OCR local (EasyOCR)."""

import io
from pathlib import Path

from PIL import Image
from pydantic import BaseModel
from pypdf import PdfReader

from sinergia.agents.processing.ocr import OcrEngine

_MIN_TEXT_LAYER_CHARS = 20


class ReadText(BaseModel):
    """Texto lido e a confiança média do OCR, quando ele foi usado."""

    text: str
    source: str
    ocr_confidence: float | None = None


class DocumentTextReader:
    """Escolhe entre a camada de texto do PDF e o OCR."""

    def __init__(self, ocr: OcrEngine) -> None:
        self._ocr = ocr

    def read(self, path: Path, mime: str | None) -> ReadText:
        """Lê o texto do arquivo arquivado pelo Agente 1."""
        if mime == "application/pdf":
            return self._read_pdf(path)
        return self._read_images([Image.open(path)])

    def _read_pdf(self, path: Path) -> ReadText:
        """Usa a camada de texto; se não houver, aplica OCR nas imagens das páginas."""
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if len(text.strip()) >= _MIN_TEXT_LAYER_CHARS:
            return ReadText(text=text, source="pdf_texto")
        images = [Image.open(io.BytesIO(img.data)) for page in reader.pages for img in page.images]
        return self._read_images(images)

    def _read_images(self, images: list[Image.Image]) -> ReadText:
        """Aplica OCR em cada imagem e junta as linhas."""
        lines = [line for image in images for line in self._ocr.read(image)]
        if not lines:
            return ReadText(text="", source="ocr", ocr_confidence=0.0)
        mean = sum(score for _, score in lines) / len(lines)
        return ReadText(
            text="\n".join(text for text, _ in lines), source="ocr", ocr_confidence=mean
        )
