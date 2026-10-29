"""OCR local com EasyOCR, com modelo de reconhecimento para português.

O OCR roda na própria máquina; a imagem do atestado nunca sai dela. Os modelos (~95 MB)
são baixados do GitHub do EasyOCR no primeiro uso e ficam em ``data/ocr_models``.

O EasyOCR devolve trechos soltos; em fotos inclinadas eles vêm fora de ordem. As linhas
são remontadas pela sobreposição vertical entre trechos vizinhos, o que tolera inclinação.
"""

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

_MIN_LINE_OVERLAP = 0.5


class OcrEngine(Protocol):
    """Contrato do motor de OCR: imagem → linhas com confiança."""

    def read(self, image: Image.Image) -> list[tuple[str, float]]:
        """Reconhece as linhas de texto da imagem, em ordem de leitura."""
        ...


class EasyOcrEngine:
    """EasyOCR em CPU; o modelo é carregado só no primeiro uso."""

    def __init__(
        self, model_dir: Path, languages: tuple[str, ...] = ("pt",), canvas_size: int = 1280
    ) -> None:
        self._model_dir = model_dir
        self._languages = list(languages)
        self._canvas_size = canvas_size
        self._reader: Any = None

    def read(self, image: Image.Image) -> list[tuple[str, float]]:
        """Reconhece os trechos e remonta as linhas."""
        with _quiet_torch():
            results = self._load().readtext(
                np.array(image.convert("RGB")), canvas_size=self._canvas_size
            )
        return group_lines(results)

    def _load(self) -> Any:
        """Carrega o modelo (e baixa, na primeira vez) para a pasta configurada."""
        if self._reader is None:
            import easyocr

            self._model_dir.mkdir(parents=True, exist_ok=True)
            self._reader = easyocr.Reader(
                self._languages,
                gpu=False,
                verbose=False,
                model_storage_directory=str(self._model_dir),
            )
        return self._reader


@contextmanager
def _quiet_torch() -> Iterator[None]:
    """Silencia avisos internos do PyTorch que não indicam problema na leitura."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def group_lines(results: list[Any]) -> list[tuple[str, float]]:
    """Agrupa os trechos em linhas, da esquerda para a direita e de cima para baixo."""
    lines: list[list[dict[str, Any]]] = []
    for box in sorted((_box(item) for item in results), key=lambda item: item["x0"]):
        line = _best_line(lines, box)
        if line is None:
            lines.append([box])
        else:
            line.append(box)
    lines.sort(key=lambda line: line[0]["y0"])
    return [
        (" ".join(b["text"] for b in line), sum(b["conf"] for b in line) / len(line))
        for line in lines
    ]


def _box(item: Any) -> dict[str, Any]:
    """Caixa delimitadora, texto e confiança de um trecho."""
    corners, text, conf = item
    xs, ys = [point[0] for point in corners], [point[1] for point in corners]
    return {"x0": min(xs), "y0": min(ys), "y1": max(ys), "text": text, "conf": float(conf)}


def _best_line(
    lines: list[list[dict[str, Any]]], box: dict[str, Any]
) -> list[dict[str, Any]] | None:
    """Linha cujo último trecho mais se sobrepõe verticalmente ao novo trecho."""
    best, best_ratio = None, 0.0
    for line in lines:
        last = line[-1]
        overlap = min(box["y1"], last["y1"]) - max(box["y0"], last["y0"])
        height = min(box["y1"] - box["y0"], last["y1"] - last["y0"]) or 1
        if overlap / height > best_ratio:
            best, best_ratio = line, overlap / height
    return best if best_ratio >= _MIN_LINE_OVERLAP else None
