"""Modelos do Agente 1: envio, laudo do arquivo e avaliação do objetivo."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from sinergia.core.domain import DocumentType


class Submission(BaseModel):
    """O que o colaborador enviou até agora (arquivo e informações)."""

    employee_id: str | None = None
    channel: str = "portal"
    declared_type: DocumentType | None = None
    absence_start: date | None = None
    file_path: str | None = None
    original_name: str | None = None

    def merge(self, reply: "Submission") -> "Submission":
        """Combina uma resposta do colaborador, mantendo o que ele não reenviou."""
        updates = reply.model_dump(exclude_none=True, exclude={"channel"})
        return self.model_copy(update=updates)


class FileIssue(StrEnum):
    """Problemas encontrados na inspeção do arquivo (R02)."""

    MISSING = "ausente"
    EMPTY = "vazio"
    UNSUPPORTED_FORMAT = "formato_nao_aceito"
    TOO_LARGE = "muito_grande"
    TOO_MANY_PAGES = "paginas_excedidas"
    CORRUPTED = "corrompido"
    PASSWORD_PROTECTED = "protegido_por_senha"
    LOW_RESOLUTION = "baixa_resolucao"
    BLANK = "sem_conteudo_visivel"
    BLURRY = "desfocado"


class FileReport(BaseModel):
    """Resultado da inspeção técnica do arquivo.

    O texto extraído serve só para classificar o documento e nunca vai para o
    estado do grafo nem para o checkpoint.
    """

    present: bool
    mime: str | None = None
    size_bytes: int = 0
    pages: int | None = None
    issues: list[FileIssue] = Field(default_factory=list)
    text: str = Field(default="", exclude=True)


class MissingItem(StrEnum):
    """Itens que impedem o dossiê de ficar completo e válido."""

    FILE = "arquivo"
    FILE_FORMAT = "formato_do_arquivo"
    FILE_UNREADABLE = "legibilidade"
    DOCUMENT_TYPE = "tipo_documento"
    DOCUMENT_TYPE_NOT_ACCEPTED = "tipo_nao_aceito"
    EMPLOYEE_ID = "matricula"
    ABSENCE_START = "data_inicio"

    @property
    def rule_id(self) -> str | None:
        """Regra de negócio associada ao item, quando houver."""
        return _ITEM_RULES.get(self)


_ITEM_RULES = {
    MissingItem.FILE: "R02",
    MissingItem.FILE_FORMAT: "R02",
    MissingItem.FILE_UNREADABLE: "R02",
    MissingItem.DOCUMENT_TYPE: "R01",
    MissingItem.DOCUMENT_TYPE_NOT_ACCEPTED: "R01",
}


class Assessment(BaseModel):
    """Avaliação do dossiê frente ao objetivo do Agente 1."""

    document_type: DocumentType | None
    missing: list[MissingItem]
    rule_hits: list[str]
    late_delivery: bool
    days_since_start: int | None

    @property
    def complete(self) -> bool:
        """O objetivo foi atingido quando nada falta."""
        return not self.missing
