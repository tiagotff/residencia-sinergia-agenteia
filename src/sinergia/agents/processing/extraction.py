"""Extração dos campos do atestado: LLM com saída estruturada ou regras por padrão.

A confiança de cada campo combina o que o extrator informa com a ancoragem no texto
(o valor aparece no documento?). O CID só é mantido se constar no documento (R09).
"""

import logging
import re
from datetime import timedelta
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from sinergia.agents.processing.grounding import grounded_fields, prepare_text
from sinergia.agents.processing.models import ExtractedFields, Extraction, parse_date
from sinergia.core.domain import DocumentType

logger = logging.getLogger(__name__)

_REGEX_CONFIDENCE = 0.9
_UNGROUNDED_CONFIDENCE = 0.3
_DATE = r"(\d{1,2}/\d{1,2}/\d{2,4})"
_PATTERNS = {
    "start_date": rf"(?:a partir de|no dia|inicio\s*:?)\s*{_DATE}",
    "end_date": rf"\bate\s*(?:o dia\s*)?{_DATE}",
    "days": r"(?<!\d)(\d{1,3})\s*(?:\([a-z ]+\)\s*)?dias?\b",
    "issue_date": rf"^[a-z .]+,\s*{_DATE}\s*$",
    "crm": r"crm\s*[:.]?\s*(\d{4,7})\s*[/-]?\s*([a-z]{2})\b",
    "cid": r"\bcid(?:-?10)?\s*[:\s]\s*([a-z]\d{2}(?:\.\d)?)",
}
_LETTER = r"[^\W\d_]"
_NAME = rf"{_LETTER}(?:{_LETTER}|[ .'])"
_NAME_PATTERNS = {
    "employee_name": rf"paciente\s*:?\s*({_NAME}{{2,80}}?)\s*(?:\n|$|,)",
    "doctor_name": rf"\b(dra?\.?\s*{_NAME}+?)\s*(?:[-–—]?\s*crm|$)",
}
"""Nomes são lidos no texto original, para manter acentos e a grafia do documento."""
_SIGNATURE = re.compile(r"assinatura|assinado|carimbo")

_SYSTEM_PROMPT = (
    "Você extrai dados de atestados médicos brasileiros. Use somente o que está escrito no "
    "texto; quando um campo não constar, deixe nulo — nunca deduza nem complete. Datas no "
    "formato DD/MM/AAAA. CRM só com dígitos e a UF com duas letras. 'signed' é verdadeiro só "
    "se o texto indicar assinatura ou carimbo do médico. 'cid' só se um código CID aparecer "
    "literalmente. Se o texto vier de OCR sem alguma letra acentuada (ex.: 'Mrcia' para "
    "'Márcia'), nos nomes você pode repor só essas letras, sem alterar nenhuma outra. "
    "Para cada campo preenchido, informe sua confiança de 0 a 1."
)


class FieldScore(BaseModel):
    """Confiança informada pelo LLM para um campo."""

    field: str
    score: float = Field(ge=0, le=1)


class LlmExtraction(BaseModel):
    """Esquema de saída estruturada pedido ao LLM."""

    employee_name: str | None = Field(None, description="Nome do paciente, como escrito")
    issue_date: str | None = Field(None, description="Data de emissão, DD/MM/AAAA")
    start_date: str | None = Field(None, description="Início do afastamento, DD/MM/AAAA")
    end_date: str | None = Field(None, description="Fim do afastamento, DD/MM/AAAA")
    days: int | None = Field(None, description="Quantidade de dias de afastamento")
    doctor_name: str | None = Field(None, description="Nome do médico")
    crm_number: str | None = Field(None, description="Número do CRM, só dígitos")
    crm_uf: str | None = Field(None, description="UF do CRM, duas letras")
    signed: bool | None = Field(None, description="Há indicação de assinatura ou carimbo")
    cid: str | None = Field(None, description="Código CID, somente se aparecer no texto")
    confidence: list[FieldScore] = Field(default_factory=list)


class FieldExtractor(Protocol):
    """Estratégia de extração: texto → campos + confiança informada."""

    name: str

    def extract(self, text: str) -> tuple[ExtractedFields, dict[str, float], str]:
        """Extrai os campos do texto; devolve também o método que de fato foi usado."""
        ...


class RegexExtractor:
    """Extração determinística por padrões; sempre disponível, sem enviar dados para fora."""

    name = "regras"

    def extract(self, text: str) -> tuple[ExtractedFields, dict[str, float], str]:
        """Aplica os padrões sobre o texto normalizado."""
        prepared = prepare_text(text)
        values = {name: _first(pattern, prepared) for name, pattern in _PATTERNS.items()}
        original = "\n".join(" ".join(line.split()) for line in text.splitlines())
        names = {name: _first(rf"(?i){p}", original) for name, p in _NAME_PATTERNS.items()}
        crm = re.search(_PATTERNS["crm"], prepared)
        fields = ExtractedFields(
            employee_name=names["employee_name"],
            issue_date=parse_date(values["issue_date"]),
            start_date=parse_date(values["start_date"]),
            end_date=parse_date(values["end_date"]),
            days=int(values["days"]) if values["days"] else None,
            doctor_name=names["doctor_name"],
            crm_number=crm.group(1) if crm else None,
            crm_uf=crm.group(2) if crm else None,
            signed=True if _SIGNATURE.search(prepared) else None,
            cid=values["cid"],
        )
        scores = dict.fromkeys(fields.model_dump(exclude_none=True), _REGEX_CONFIDENCE)
        return fields, scores, self.name


class LlmExtractor:
    """Extração com LLM e saída estruturada; campos faltantes são completados pelas regras."""

    name = "llm"

    def __init__(self, model: BaseChatModel, fallback: RegexExtractor) -> None:
        self._structured = model.with_structured_output(LlmExtraction)
        self._fallback = fallback

    def extract(self, text: str) -> tuple[ExtractedFields, dict[str, float], str]:
        """Pede os campos ao LLM; em qualquer falha, usa só as regras."""
        try:
            answer = self._structured.invoke([SystemMessage(_SYSTEM_PROMPT), HumanMessage(text)])
            fields = ExtractedFields.model_validate(answer.model_dump(exclude={"confidence"}))
        except Exception as exc:  # noqa: BLE001 — falha do provedor nunca derruba o processamento
            logger.warning("Extração por LLM falhou (%s); usando regras.", type(exc).__name__)
            logger.debug("Detalhe da falha do LLM", exc_info=True)
            return self._fallback.extract(text)
        scores = {item.field: item.score for item in answer.confidence}
        merged, confidence = self._complete_with_rules(fields, scores, text)
        return merged, confidence, self.name

    def _complete_with_rules(
        self, fields: ExtractedFields, scores: dict[str, float], text: str
    ) -> tuple[ExtractedFields, dict[str, float]]:
        """Preenche com as regras os campos que o LLM deixou nulos."""
        rule_fields, rule_scores, _ = self._fallback.extract(text)
        missing = {
            name: value
            for name, value in rule_fields.model_dump().items()
            if value is not None and getattr(fields, name) is None
        }
        merged = fields.model_copy(update=missing)
        confidence = {
            name: scores.get(name, _REGEX_CONFIDENCE) for name in ExtractedFields.model_fields
        }
        confidence.update({name: rule_scores[name] for name in missing})
        present = merged.model_dump(exclude_none=True)
        return merged, {name: score for name, score in confidence.items() if name in present}


def build_extraction(
    extractor: FieldExtractor,
    text: str,
    employee_id: str | None,
    document_type: DocumentType | None,
    ocr_confidence: float | None,
) -> Extraction:
    """Extrai, ancora no texto, aplica R09 e deriva fim/dias quando possível."""
    fields, reported, method = extractor.extract(text)
    grounded = grounded_fields(fields, prepare_text(text))
    cid_discarded = fields.cid is not None and not grounded.get("cid", False)
    if cid_discarded:
        fields = fields.model_copy(update={"cid": None})
    confidence = _confidence(reported, grounded)
    fields, derived = derive_period(fields)
    return Extraction(
        employee_id=employee_id,
        document_type=document_type,
        fields=fields,
        confidence={name: confidence[name] for name in confidence if name != "cid" or fields.cid},
        method=method,
        derived=derived,
        cid_discarded=cid_discarded,
        ocr_confidence=ocr_confidence,
    )


def _confidence(reported: dict[str, float], grounded: dict[str, bool]) -> dict[str, float]:
    """Confiança do campo: a informada pelo extrator, se o valor aparece no texto."""
    return {
        name: round(reported.get(name, _REGEX_CONFIDENCE), 3)
        if is_grounded
        else _UNGROUNDED_CONFIDENCE
        for name, is_grounded in grounded.items()
    }


def derive_period(fields: ExtractedFields) -> tuple[ExtractedFields, list[str]]:
    """Calcula o fim a partir dos dias (ou os dias a partir do fim), marcando como derivado."""
    if fields.start_date and fields.days and not fields.end_date:
        end = fields.start_date + timedelta(days=fields.days - 1)
        return fields.model_copy(update={"end_date": end}), ["end_date"]
    if fields.start_date and fields.end_date and fields.days is None:
        days = (fields.end_date - fields.start_date).days + 1
        return fields.model_copy(update={"days": max(days, 0)}), ["days"]
    return fields, []


def _first(pattern: str, text: str) -> str | None:
    """Primeiro grupo do padrão no texto (linha a linha para âncoras ^ e $)."""
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def build_field_extractor(model: BaseChatModel | None) -> FieldExtractor:
    """LLM quando configurado; senão, só as regras."""
    rules = RegexExtractor()
    return rules if model is None else LlmExtractor(model, rules)
