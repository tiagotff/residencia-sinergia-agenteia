"""Vocabulário de domínio compartilhado entre os agentes."""

from enum import StrEnum


class DocumentType(StrEnum):
    """Tipos de documento que o colaborador pode enviar."""

    MEDICAL_CERTIFICATE = "atestado_medico"
    ATTENDANCE_STATEMENT = "declaracao_comparecimento"
    COMPANION_CERTIFICATE = "atestado_acompanhante"
    OTHER = "outro"
    UNKNOWN = "desconhecido"

    @property
    def label(self) -> str:
        """Nome do tipo para mensagens ao colaborador."""
        return _DOCUMENT_LABELS[self]


_DOCUMENT_LABELS = {
    DocumentType.MEDICAL_CERTIFICATE: "atestado médico",
    DocumentType.ATTENDANCE_STATEMENT: "declaração de comparecimento",
    DocumentType.COMPANION_CERTIFICATE: "atestado de acompanhante",
    DocumentType.OTHER: "outro documento",
    DocumentType.UNKNOWN: "documento",
}


class CaseStatus(StrEnum):
    """Situação de um caso ao longo do fluxo."""

    AWAITING_EMPLOYEE = "aguardando_colaborador"
    RECEIVED = "recebido"
    PENDING_HR = "pendente_rh"
