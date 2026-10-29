"""Repositório de arquivos: área de recebimento temporária e arquivo definitivo."""

import hashlib
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

_EXTENSIONS = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}


class StoredFile(BaseModel):
    """Arquivo arquivado no repositório definitivo."""

    path: str
    sha256: str


class FileStore:
    """Guarda arquivos recebidos fora do banco, separados por estágio."""

    def __init__(self, root: Path) -> None:
        self._staging = root / "staging"
        self._repository = root / "repository"

    def stage(self, content: bytes, original_name: str) -> Path:
        """Grava o upload na área temporária e devolve o caminho."""
        self._staging.mkdir(parents=True, exist_ok=True)
        suffix = Path(original_name).suffix.lower()[:10]
        path = self._staging / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(content)
        return path

    def archive(self, staged: Path, protocol: str, mime: str, when: datetime) -> StoredFile:
        """Move o arquivo aceito para o repositório, nomeado pelo protocolo."""
        folder = self._repository / f"{when:%Y}" / f"{when:%m}"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{protocol}{_EXTENSIONS.get(mime, '.bin')}"
        shutil.move(staged, target)
        return StoredFile(path=str(target), sha256=_sha256(target))

    def discard(self, staged: Path | None) -> None:
        """Remove um arquivo temporário que não será usado."""
        if staged is not None:
            staged.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    """Calcula o hash do arquivo, para provar integridade na auditoria."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
