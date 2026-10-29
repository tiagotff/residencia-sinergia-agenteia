"""Modelos do Agente 2: campos extraídos, verificação do CRM, validação e revisão."""

import re
from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from sinergia.core.dates import parse_date
from sinergia.core.domain import EXTRACTED_FIELDS, AbsenceStatus, DocumentType

__all__ = ["parse_date"]


class ExtractedFields(BaseModel):
    """Campos do documento; ``None`` quando não constam (o agente nunca adivinha)."""

    employee_name: str | None = None
    issue_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None
    days: int | None = Field(default=None, ge=0, le=365)
    doctor_name: str | None = None
    crm_number: str | None = None
    crm_uf: str | None = None
    signed: bool | None = None
    cid: str | None = None

    @field_validator("issue_date", "start_date", "end_date", mode="before")
    @classmethod
    def _dates(cls, value: Any) -> date | None:
        """Aceita datas nos formatos brasileiros e ISO."""
        return parse_date(value)

    @field_validator("crm_number", mode="before")
    @classmethod
    def _crm_digits(cls, value: Any) -> str | None:
        """Mantém só os dígitos do CRM."""
        digits = re.sub(r"\D", "", str(value)) if value is not None else ""
        return digits or None

    @field_validator("crm_uf", "cid", mode="before")
    @classmethod
    def _upper(cls, value: Any) -> str | None:
        """Sigla da UF e código CID em maiúsculas."""
        return str(value).strip().upper() or None if value is not None else None


class Extraction(BaseModel):
    """Resultado da extração, com a confiança de cada campo e a origem dos valores."""

    employee_id: str | None
    document_type: DocumentType | None
    fields: ExtractedFields
    confidence: dict[str, float] = Field(default_factory=dict)
    method: str
    derived: list[str] = Field(default_factory=list)
    human_verified: list[str] = Field(default_factory=list)
    cid_discarded: bool = False
    ocr_confidence: float | None = None


class CrmStatus(StrEnum):
    """Resultado da consulta do CRM (R06)."""

    REGULAR = "regular"
    IRREGULAR = "irregular"
    NOT_FOUND = "nao_encontrado"
    NOT_VERIFIED = "nao_verificado"


class CrmCheck(BaseModel):
    """Situação do CRM e de onde ela veio."""

    status: CrmStatus
    situation: str | None = None
    detail: str
    source: str


class Violation(BaseModel):
    """Regra violada, com a explicação e os campos envolvidos."""

    rule_id: str
    message: str
    fields: list[str] = Field(default_factory=list)


class Validation(BaseModel):
    """Resultado das regras R04–R08 sobre o registro."""

    violations: list[Violation]

    @property
    def valid(self) -> bool:
        """O registro passou em todas as regras."""
        return not self.violations

    @property
    def rule_ids(self) -> list[str]:
        """Regras violadas, sem repetição."""
        return sorted({violation.rule_id for violation in self.violations})

    @property
    def status(self) -> AbsenceStatus:
        """Campo obrigatório ausente → pendente; demais violações → revisão humana."""
        if self.valid:
            return AbsenceStatus.VALID
        if "R04" in self.rule_ids:
            return AbsenceStatus.PENDING
        return AbsenceStatus.HUMAN_REVIEW


class Escalation(BaseModel):
    """Encaminhamento com prazo legal para o Agente 4 e para a área responsável."""

    rule_id: str
    kind: str
    target_area: str
    reason: str


class ReviewDecision(BaseModel):
    """Decisão do profissional sobre um caso em revisão."""

    decision: Literal["aprovar", "invalidar"]
    reviewer: str = Field(min_length=1)
    corrections: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None

    @field_validator("corrections")
    @classmethod
    def _known_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Só aceita correções em campos que o agente extrai."""
        unknown = set(value) - set(EXTRACTED_FIELDS)
        if unknown:
            raise ValueError(f"Campos desconhecidos na correção: {sorted(unknown)}")
        return value
