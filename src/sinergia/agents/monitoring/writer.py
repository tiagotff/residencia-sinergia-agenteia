"""Redação dos alertas: a explicação sempre traz a regra, a métrica, o limiar e o período.

O texto-base é determinístico. Com LLM configurado, ele é reescrito em linguagem mais
fluida, com regras de segurança:
- o LLM recebe marcadores no lugar do grupo de CID e do pseudônimo, nunca os valores;
- todos os números e marcadores precisam voltar intactos, senão vale o texto-base.
"""

import logging
import re
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from sinergia.data.alerts import Alert

logger = logging.getLogger(__name__)

_CID = "{GRUPO_CID}"
_PERSON = "{COLABORADOR}"
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_SYSTEM_PROMPT = (
    "Você reescreve alertas de saúde ocupacional para o SESMT, em português do Brasil, em até "
    "60 palavras e em tom técnico e neutro. Mantenha exatamente todos os números, datas e os "
    "marcadores entre chaves. Não acrescente causas, diagnósticos nem recomendações que não "
    "estejam no texto. Nunca culpe pessoas. Responda só com o texto reescrito."
)


class AlertWriter(Protocol):
    """Contrato da redação dos alertas."""

    def explain(self, alert: Alert) -> str:
        """Texto explicável do alerta."""
        ...


class TemplateWriter:
    """Explicações determinísticas, uma por regra."""

    def explain(self, alert: Alert) -> str:
        """Preenche o modelo da regra com os números do alerta."""
        return _fill(base_text(alert), alert)


class LlmWriter:
    """Reescreve o texto-base com o LLM, sem expor dados sensíveis."""

    def __init__(self, model: BaseChatModel, fallback: TemplateWriter) -> None:
        self._model = model
        self._fallback = fallback

    def explain(self, alert: Alert) -> str:
        """Usa o LLM quando a resposta preserva números e marcadores."""
        base = base_text(alert)
        try:
            reply = self._model.invoke([SystemMessage(_SYSTEM_PROMPT), HumanMessage(base)])
        except Exception as exc:  # noqa: BLE001 — falha do provedor nunca derruba o monitoramento
            logger.warning("LLM indisponível (%s); usando texto padrão.", type(exc).__name__)
            return self._fallback.explain(alert)
        text = str(reply.content).strip()
        return _fill(text, alert) if preserves(base, text) else self._fallback.explain(alert)


def preserves(base: str, rewritten: str) -> bool:
    """O texto reescrito mantém todos os números e marcadores do original."""
    tokens = _NUMBER.findall(base) + [m for m in (_CID, _PERSON) if m in base]
    return bool(rewritten) and len(rewritten) <= 800 and all(t in rewritten for t in tokens)


def base_text(alert: Alert) -> str:
    """Texto-base por regra, com marcadores no lugar de dados sensíveis."""
    return _TEXTS[alert.rule_id](alert)


def _period(alert: Alert) -> str:
    """Período do alerta em DD/MM/AAAA."""
    return f"{alert.period_start:%d/%m/%Y} a {alert.period_end:%d/%m/%Y}"


def _a01(alert: Alert) -> str:
    """Pico de afastamentos no setor."""
    return (
        f"A taxa de afastamento do setor {alert.scope} foi {_pct(alert.value)} em "
        f"{_period(alert)}, acima do limiar de {_pct(alert.threshold)}; a média das semanas "
        f"anteriores foi {_pct(alert.reference or 0)} ({alert.group_size} pessoas no grupo)."
    )


def _a02(alert: Alert) -> str:
    """Mesmo grupo de CID concentrado no setor ou turno."""
    return (
        f"{int(alert.value)} pessoas do {_scope(alert)} tiveram afastamentos do grupo de CID "
        f"{_CID} em {_period(alert)} (mínimo para alerta: {int(alert.threshold)}; "
        f"{alert.group_size} pessoas no grupo). Avaliar possível relação com o trabalho."
    )


def _a03(alert: Alert) -> str:
    """Cobertura baixa em função crítica."""
    return (
        f"A função crítica {alert.scope} está com {_pct(alert.value)} da equipe disponível em "
        f"{alert.period_end:%d/%m/%Y}, abaixo do mínimo de {_pct(alert.threshold)} "
        f"({alert.details.get('ausentes', 0)} de {alert.group_size} ausentes)."
    )


def _a04(alert: Alert) -> str:
    """Mesma causa se aproximando do limite do INSS."""
    return (
        f"{_PERSON} soma {int(alert.value)} dias de afastamento pelo grupo de CID {_CID} em "
        f"{_period(alert)}; a partir de {alert.details.get('limite_legal', 15)} dias o caso "
        f"segue para o INSS. Pendência administrativa preventiva."
    )


_TEXTS = {"A01": _a01, "A02": _a02, "A03": _a03, "A04": _a04}


def _fill(text: str, alert: Alert) -> str:
    """Troca os marcadores pelos valores reais, que nunca passaram pelo LLM."""
    return text.replace(_CID, str(alert.details.get("grupo_cid", ""))).replace(
        _PERSON, f"O colaborador {alert.scope}"
    )


def _scope(alert: Alert) -> str:
    """'setor X' ou 'turno Y'."""
    return f"{alert.scope_type} {alert.scope}"


def _pct(value: float) -> str:
    """Fração como porcentagem com uma casa decimal."""
    return f"{value * 100:.1f}%".replace(".", ",")


def build_writer(model: BaseChatModel | None) -> AlertWriter:
    """LLM quando configurado; senão, só o texto-base."""
    template = TemplateWriter()
    return template if model is None else LlmWriter(model, template)
