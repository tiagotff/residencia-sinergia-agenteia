"""Ancoragem: confere se cada valor extraído aparece de fato no texto do documento.

É o que impede o agente de "adivinhar" (R08) e de registrar CID que não consta no
documento (R09). Vale tanto para a extração por LLM quanto para a por regras.
"""

import re
from datetime import date
from typing import Any

from sinergia.agents.processing.models import ExtractedFields
from sinergia.agents.reception.classifier import normalize

_SIGNATURE_TERMS = ("assinatura", "assinado", "carimbo")
_NAME_FIELDS = ("employee_name", "doctor_name")


def prepare_text(text: str) -> str:
    """Normaliza o texto: minúsculas, sem acentos, e 'o' lido no lugar de '0' em números."""
    lines = (" ".join(normalize(line).split()) for line in text.splitlines())
    joined = "\n".join(line for line in lines if line)
    return re.sub(r"\b[0-9o]*\d[0-9o]*\b", lambda m: m.group().replace("o", "0"), joined)


def grounded_fields(fields: ExtractedFields, prepared: str) -> dict[str, bool]:
    """Para cada campo preenchido, indica se o valor aparece no texto."""
    compact = re.sub(r"\s+", "", prepared)
    values = fields.model_dump(exclude_none=True)
    return {name: _is_grounded(name, value, prepared, compact) for name, value in values.items()}


def _is_grounded(name: str, value: Any, prepared: str, compact: str) -> bool:
    """Regra de ancoragem conforme o tipo do campo."""
    if isinstance(value, bool):
        return (not value) or any(term in prepared for term in _SIGNATURE_TERMS)
    if isinstance(value, date):
        return any(form in compact for form in _date_forms(value))
    if isinstance(value, int):
        return re.search(rf"(?<!\d){value}(?!\d)", prepared) is not None
    if name in _NAME_FIELDS:
        tokens = [token for token in str(value).split() if len(normalize(token)) >= 3]
        return bool(tokens) and all(_token_found(token, compact) for token in tokens)
    return normalize(str(value)).replace(" ", "") in compact


def _token_found(token: str, compact: str) -> bool:
    """A palavra aparece no texto, com ou sem as letras acentuadas que o OCR descarta.

    O OCR padrão não reconhece letras acentuadas e as omite ("Márcia" vira "Mrcia").
    As demais letras precisam bater exatamente.
    """
    return any(form and form in compact for form in ocr_forms(token))


def ocr_forms(token: str) -> set[str]:
    """Formas aceitas de uma palavra: sem acentos e sem as letras acentuadas."""
    cleaned = token.lower().strip(".,;:")
    without_accented = "".join(char for char in cleaned if char.isascii())
    return {normalize(cleaned), without_accented}


def _date_forms(value: date) -> list[str]:
    """Formas comuns de escrever uma data num atestado."""
    return [
        value.strftime("%d/%m/%Y"),
        value.strftime("%d/%m/%y"),
        value.strftime("%d-%m-%Y"),
        value.strftime("%d.%m.%Y"),
        f"{value.day}/{value.month}/{value.year}",
    ]
