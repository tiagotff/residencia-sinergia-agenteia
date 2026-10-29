"""Classificação do tipo de documento pela camada de texto (apoio à R01).

Regras por palavras-chave, explicáveis e sem LLM: o texto do atestado não sai da
máquina nesta etapa. Sem texto (foto ou PDF escaneado), o tipo fica desconhecido e
vale o que o colaborador declarou.
"""

import unicodedata

from sinergia.core.domain import DocumentType

_COMPANION_TERMS = ("acompanhante", "acompanhar", "acompanhamento")
_ATTENDANCE_TERMS = ("comparecimento", "compareceu", "esteve presente")
_CERTIFICATE_TERMS = ("atestado", "atesto")
_ABSENCE_TERMS = ("afastamento", "afastado", "repouso", "dias")


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para comparar palavras-chave."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def classify_document(text: str) -> DocumentType:
    """Classifica o documento pelo texto extraído."""
    content = normalize(text)
    if not content.strip():
        return DocumentType.UNKNOWN
    if _has_any(content, _COMPANION_TERMS) and _has_any(content, _CERTIFICATE_TERMS):
        return DocumentType.COMPANION_CERTIFICATE
    if _has_any(content, _ATTENDANCE_TERMS):
        return DocumentType.ATTENDANCE_STATEMENT
    if _has_any(content, _CERTIFICATE_TERMS) and _has_any(content, _ABSENCE_TERMS):
        return DocumentType.MEDICAL_CERTIFICATE
    return DocumentType.OTHER


def _has_any(content: str, terms: tuple[str, ...]) -> bool:
    """Indica se ao menos um termo aparece no texto."""
    return any(term in content for term in terms)
