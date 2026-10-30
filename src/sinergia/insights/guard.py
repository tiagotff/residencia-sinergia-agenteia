"""Conferência determinística do relatório (I01), depois do revisor de privacidade da crew.

O texto só passa se: não tiver matrícula, pseudônimo, código CID nem nome de grupo pequeno;
não usar termos estigmatizantes; e todo número estiver nos fatos (o LLM não inventa dado).
"""

import re

from sinergia.core.rules import RuleCatalog

_PSEUDONYM = re.compile(r"\bP-[0-9a-f]{10}\b")
_CID = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b")
_NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")  # "A01" é regra, não número


def check_report(
    text: str,
    facts_text: str,
    forbidden: tuple[list[str], list[str]],
    rules: RuleCatalog,
) -> list[str]:
    """Problemas encontrados (vazio = aprovado); ``forbidden`` = (matrículas, grupos ocultos)."""
    employee_ids, hidden_groups = forbidden
    issues = []
    if len(text) > rules.insights.max_report_chars:
        issues.append("Relatório longo demais.")
    if _PSEUDONYM.search(text):
        issues.append("Contém pseudônimo de colaborador.")
    cids = {code for code in _CID.findall(text) if code not in rules.catalog}
    if cids:
        issues.append(f"Contém código de CID: {', '.join(sorted(cids))}.")
    issues += _mentions(text, employee_ids, "Contém matrícula")
    issues += _mentions(text, hidden_groups, "Cita grupo pequeno demais (A05)")
    issues += _mentions(text, rules.insights.stigmatizing_terms, "Usa termo estigmatizante")
    issues += _unknown_numbers(text, facts_text, rules.insights.allowed_small_numbers)
    return issues


def _mentions(text: str, words: list[str], label: str) -> list[str]:
    """Palavras proibidas que aparecem no texto (palavra inteira, sem diferenciar maiúsculas)."""
    found = [w for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text, re.IGNORECASE)]
    return [f"{label}: {', '.join(found)}."] if found else []


def _unknown_numbers(text: str, facts_text: str, small: int) -> list[str]:
    """Números do texto que não estão nos fatos (inteiros pequenos são permitidos)."""
    allowed = set(_NUMBER.findall(facts_text)) | {str(n) for n in range(small + 1)}
    unknown = sorted({n for n in _NUMBER.findall(text) if n not in allowed})
    return [f"Números que não estão nos fatos: {', '.join(unknown)}."] if unknown else []
