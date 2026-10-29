"""Mensagens do Agente 1 para o colaborador.

As mensagens nascem de modelos de texto fixos. Com LLM configurado, o pedido do que
falta é reescrito em tom de conversa; o LLM recebe só esse texto, nunca o documento,
e qualquer falha volta para o modelo fixo. Protocolo e prazos nunca passam pelo LLM.
"""

import logging
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from sinergia.agents.reception.models import MissingItem
from sinergia.core.domain import DocumentType
from sinergia.core.rules import ReceptionRules

logger = logging.getLogger(__name__)

_MAX_LLM_MESSAGE_CHARS = 900

_SYSTEM_PROMPT = (
    "Você é o assistente de recepção de atestados de uma empresa. Reescreva o pedido abaixo "
    "em português do Brasil, em tom cordial e direto, com no máximo 80 palavras. Mantenha "
    "todos os itens pedidos, não acrescente exigências, não peça dados de saúde e não "
    "invente prazos. Responda só com a mensagem ao colaborador."
)


class MessageComposer(Protocol):
    """Contrato das mensagens do Agente 1."""

    def request_missing(self, items: list[MissingItem]) -> str:
        """Pede ao colaborador o que falta no dossiê."""
        ...

    def confirm_receipt(self, protocol: str, document_type: DocumentType, late: bool) -> str:
        """Confirma o recebimento com o protocolo."""
        ...

    def hand_over_to_hr(self, protocol: str) -> str:
        """Avisa que o caso seguiu para o RH."""
        ...


class TemplateComposer:
    """Mensagens determinísticas a partir de modelos de texto."""

    def __init__(self, rules: ReceptionRules) -> None:
        self._rules = rules

    def request_missing(self, items: list[MissingItem]) -> str:
        """Lista, em tópicos, o que o colaborador precisa enviar."""
        lines = [f"- {self._item_text(item)}" for item in items]
        return "Para concluir o recebimento, preciso de:\n" + "\n".join(lines)

    def confirm_receipt(self, protocol: str, document_type: DocumentType, late: bool) -> str:
        """Confirma o recebimento e, se for o caso, informa a entrega fora do prazo."""
        text = (
            f"Documento recebido ({document_type.label}). Protocolo {protocol}. "
            "Use esse número para acompanhar a solicitação."
        )
        if late:
            days = self._rules.delivery_deadline_days
            text += f" A entrega passou do prazo de {days} dias da política; o RH foi avisado."
        return text

    def hand_over_to_hr(self, protocol: str) -> str:
        """Explica que, sem as informações pendentes, o RH assume o caso."""
        return (
            "Não recebemos todas as informações pendentes, então sua solicitação seguiu para "
            f"o RH, que vai entrar em contato. Protocolo {protocol}."
        )

    def _item_text(self, item: MissingItem) -> str:
        """Texto do pedido para um item pendente, com os limites vigentes."""
        return _ITEM_TEXTS[item].format(
            max_mb=f"{self._rules.max_file_size_mb:g}", max_pages=self._rules.max_pdf_pages
        )


_ACCEPTED = "atestado médico, declaração de comparecimento ou atestado de acompanhante"
_ITEM_TEXTS = {
    MissingItem.FILE: "o arquivo do documento (PDF, JPG ou PNG)",
    MissingItem.FILE_FORMAT: "o arquivo em PDF, JPG ou PNG, com até {max_mb} MB "
    "e até {max_pages} páginas",
    MissingItem.FILE_UNREADABLE: "um novo arquivo legível: foto nítida, bem iluminada e sem "
    "cortes, ou o PDF original",
    MissingItem.DOCUMENT_TYPE: f"o tipo do documento: {_ACCEPTED}",
    MissingItem.DOCUMENT_TYPE_NOT_ACCEPTED: f"o documento correto — aceitamos {_ACCEPTED}",
    MissingItem.EMPLOYEE_ID: "sua matrícula",
    MissingItem.ABSENCE_START: "a data de início do afastamento (AAAA-MM-DD)",
}


class LlmComposer:
    """Reescreve o pedido com o LLM e cai para o modelo fixo em qualquer falha."""

    def __init__(self, model: BaseChatModel, fallback: TemplateComposer) -> None:
        self._model = model
        self._fallback = fallback

    def request_missing(self, items: list[MissingItem]) -> str:
        """Pede o que falta em tom de conversa."""
        base = self._fallback.request_missing(items)
        try:
            reply = self._model.invoke([SystemMessage(_SYSTEM_PROMPT), HumanMessage(base)])
        except Exception as exc:  # noqa: BLE001 — falha do provedor nunca derruba a recepção
            logger.warning("LLM indisponível (%s); usando mensagem padrão.", type(exc).__name__)
            logger.debug("Detalhe da falha do LLM", exc_info=True)
            return base
        text = str(reply.content).strip()
        return text if 0 < len(text) <= _MAX_LLM_MESSAGE_CHARS else base

    def confirm_receipt(self, protocol: str, document_type: DocumentType, late: bool) -> str:
        """Confirmação factual, sem LLM."""
        return self._fallback.confirm_receipt(protocol, document_type, late)

    def hand_over_to_hr(self, protocol: str) -> str:
        """Aviso factual, sem LLM."""
        return self._fallback.hand_over_to_hr(protocol)


def build_composer(rules: ReceptionRules, model: BaseChatModel | None) -> MessageComposer:
    """Usa o LLM quando configurado; senão, só os modelos fixos."""
    template = TemplateComposer(rules)
    return template if model is None else LlmComposer(model, template)
