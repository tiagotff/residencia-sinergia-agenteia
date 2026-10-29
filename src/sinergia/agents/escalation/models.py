"""Modelos do Agente 4: demanda a encaminhar, proposta pontuada e decisão humana."""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class Demand(BaseModel):
    """Algo que precisa de um responsável: regra R10–R13 de um caso ou alerta A01–A04.

    ``health_detail`` (grupo de CID) só chega a destinos de saúde. ``max_detail`` limita o
    que a origem permite: um alerta nunca reidentifica pessoas.
    """

    key: str
    rule_id: str
    subject: str
    source_ref: str
    deadline: date | None = None
    max_detail: str
    facts: dict[str, Any] = Field(default_factory=dict)
    health_detail: str | None = None


class Proposal(BaseModel):
    """Melhor alternativa para um destino, com a conta que levou a ela."""

    destination: str
    urgency: str
    detail: str
    utility: float
    breakdown: dict[str, float]
    primary: bool = False


class EscalationDecision(BaseModel):
    """Confirmação humana: tudo é confirmado, exceto o que for cancelado ou redirecionado."""

    reviewer: str = Field(min_length=2)
    cancel: list[int] = Field(default_factory=list)
    redirect: dict[int, str] = Field(default_factory=dict)
    note: str | None = None
