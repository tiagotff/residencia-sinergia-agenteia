"""Catálogo versionado de regras de negócio, carregado de YAML."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from sinergia.core.domain import EXTRACTED_FIELDS, DocumentType
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


class ProcessingRules(BaseModel):
    """Parâmetros do Agente 2 — Processamento (R04–R11)."""

    required_fields: dict[DocumentType, list[str]]
    issue_after_start_tolerance_days: int = Field(ge=0)
    min_field_confidence: float = Field(ge=0, le=1)
    min_ocr_confidence: float = Field(ge=0, le=1)
    inss_threshold_days: int = Field(gt=0)
    same_cause_window_days: int = Field(gt=0)

    @field_validator("required_fields")
    @classmethod
    def _known_fields(cls, value: dict[DocumentType, list[str]]) -> dict[DocumentType, list[str]]:
        """Recusa nomes de campo que o extrator não conhece."""
        unknown = {name for names in value.values() for name in names} - set(EXTRACTED_FIELDS)
        if unknown:
            raise ValueError(f"Campos desconhecidos em required_fields: {sorted(unknown)}")
        return value


class MonitoringRules(BaseModel):
    """Parâmetros do Agente 3 — Monitoramento (A01–A05)."""

    min_group_size: int = Field(gt=0)
    baseline_weeks: int = Field(gt=0)
    min_baseline_weeks: int = Field(gt=0)
    spike_std_factor: float = Field(ge=0)
    min_rate_increase: float = Field(ge=0)
    cid_window_days: int = Field(gt=0)
    cid_min_cases: int = Field(gt=1)
    min_critical_coverage: float = Field(gt=0, le=1)
    same_cause_alert_days: int = Field(gt=0)


class RuleCatalog(BaseModel):
    """Conjunto completo de regras com a versão que será registrada na auditoria."""

    version: str
    catalog: dict[str, RuleInfo]
    reception: ReceptionRules
    processing: ProcessingRules
    monitoring: MonitoringRules


def load_rules(path: Path) -> RuleCatalog:
    """Lê e valida o arquivo de regras."""
    if not path.exists():
        raise ConfigurationError(f"Arquivo de regras não encontrado: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return RuleCatalog.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"Arquivo de regras inválido ({path}): {exc}") from exc
