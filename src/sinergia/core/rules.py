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


class Urgency(BaseModel):
    """Nível de urgência: prazo para a área agir e custo de interromper o trabalho."""

    sla_days: int = Field(gt=0)
    cost: float = Field(ge=0)


class DemandRules(BaseModel):
    """Como tratar um tipo de demanda (regra R10–R13 ou alerta A01–A04)."""

    title: str
    health: bool
    min_detail: str
    severity: float = Field(ge=0)
    default_deadline_days: int | None = Field(default=None, ge=0)
    competence: dict[str, float]


class EscalationRules(BaseModel):
    """Parâmetros do Agente 4 — Escalonamento (função de utilidade, R12–R13)."""

    min_utility: float
    weights: dict[str, float]
    urgencies: dict[str, Urgency]
    detail_levels: dict[str, float]
    health_destinations: list[str]
    return_exam_min_days: int = Field(gt=0)
    occupational_cid_prefixes: list[str]
    chain: dict[str, str]
    max_reescalations: int = Field(ge=0)
    demands: dict[str, DemandRules]

    @field_validator("weights")
    @classmethod
    def _weights(cls, value: dict[str, float]) -> dict[str, float]:
        """Exige os quatro pesos da função de utilidade."""
        missing = {"competence", "privacy", "urgency", "deadline"} - set(value)
        if missing:
            raise ValueError(f"Pesos ausentes em escalation.weights: {sorted(missing)}")
        return value

    @property
    def max_sla(self) -> int:
        """Maior SLA, usado para normalizar o atraso."""
        return max(urgency.sla_days for urgency in self.urgencies.values())


class InsightsRules(BaseModel):
    """Parâmetros da crew de insights (I01)."""

    period_days: int = Field(gt=0)
    trend_weeks: int = Field(gt=0)
    max_report_chars: int = Field(gt=0)
    allowed_small_numbers: int = Field(ge=0)
    stigmatizing_terms: list[str]


class RuleCatalog(BaseModel):
    """Conjunto completo de regras com a versão que será registrada na auditoria."""

    version: str
    catalog: dict[str, RuleInfo]
    reception: ReceptionRules
    processing: ProcessingRules
    monitoring: MonitoringRules
    escalation: EscalationRules
    insights: InsightsRules


def load_rules(path: Path) -> RuleCatalog:
    """Lê e valida o arquivo de regras."""
    if not path.exists():
        raise ConfigurationError(f"Arquivo de regras não encontrado: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return RuleCatalog.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"Arquivo de regras inválido ({path}): {exc}") from exc
