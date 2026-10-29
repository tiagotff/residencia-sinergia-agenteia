"""Catálogo versionado de regras de negócio, carregado de YAML."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from sinergia.core.domain import DocumentType
from sinergia.core.errors import ConfigurationError


class RuleInfo(BaseModel):
    """Descrição de uma regra do catálogo."""

    agent: str
    description: str


class ReceptionRules(BaseModel):
    """Parâmetros do Agente 1 — Recepção (R01–R03)."""

    accepted_document_types: list[DocumentType]
    accepted_mime_types: list[str]
    max_file_size_mb: float = Field(gt=0)
    max_pdf_pages: int = Field(gt=0)
    min_image_width_px: int = Field(gt=0)
    min_image_height_px: int = Field(gt=0)
    min_image_contrast: float = Field(ge=0)
    min_image_sharpness: float = Field(ge=0)
    delivery_deadline_days: int = Field(ge=0)
    max_resubmission_attempts: int = Field(gt=0)

    @property
    def max_file_size_bytes(self) -> int:
        """Tamanho máximo do arquivo em bytes."""
        return int(self.max_file_size_mb * 1024 * 1024)


class RuleCatalog(BaseModel):
    """Conjunto completo de regras com a versão que será registrada na auditoria."""

    version: str
    catalog: dict[str, RuleInfo]
    reception: ReceptionRules


def load_rules(path: Path) -> RuleCatalog:
    """Lê e valida o arquivo de regras."""
    if not path.exists():
        raise ConfigurationError(f"Arquivo de regras não encontrado: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return RuleCatalog.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"Arquivo de regras inválido ({path}): {exc}") from exc
