"""Testes das mensagens do Agente 1, com e sem LLM."""

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from sinergia.agents.reception.messages import LlmComposer, TemplateComposer, build_composer
from sinergia.agents.reception.models import MissingItem
from sinergia.core.domain import DocumentType
from sinergia.core.rules import RuleCatalog


class _BrokenModel(FakeListChatModel):
    def _call(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError("provedor fora do ar")


def test_template_lists_every_missing_item(rules: RuleCatalog) -> None:
    text = TemplateComposer(rules.reception).request_missing(
        [MissingItem.EMPLOYEE_ID, MissingItem.ABSENCE_START]
    )
    assert "matrícula" in text
    assert "data de início" in text


def test_receipt_mentions_protocol_and_late_delivery(rules: RuleCatalog) -> None:
    composer = TemplateComposer(rules.reception)
    text = composer.confirm_receipt("SNG-1", DocumentType.MEDICAL_CERTIFICATE, late=True)
    assert "SNG-1" in text
    assert "atestado médico" in text
    assert "prazo" in text


def test_llm_rewrites_request(rules: RuleCatalog) -> None:
    model = FakeListChatModel(responses=["Oi! Pode me mandar sua matrícula?"])
    composer = build_composer(rules.reception, model)
    assert isinstance(composer, LlmComposer)
    assert composer.request_missing([MissingItem.EMPLOYEE_ID]) == (
        "Oi! Pode me mandar sua matrícula?"
    )


def test_llm_failure_falls_back_to_template(rules: RuleCatalog) -> None:
    template = TemplateComposer(rules.reception)
    composer = LlmComposer(_BrokenModel(responses=["x"]), template)
    items = [MissingItem.EMPLOYEE_ID]
    assert composer.request_missing(items) == template.request_missing(items)


def test_empty_llm_answer_falls_back_to_template(rules: RuleCatalog) -> None:
    template = TemplateComposer(rules.reception)
    composer = LlmComposer(FakeListChatModel(responses=["   "]), template)
    items = [MissingItem.FILE]
    assert composer.request_missing(items) == template.request_missing(items)


def test_protocol_never_goes_through_llm(rules: RuleCatalog) -> None:
    model = FakeListChatModel(responses=["texto inventado"])
    composer = LlmComposer(model, TemplateComposer(rules.reception))
    text = composer.confirm_receipt("SNG-9", DocumentType.MEDICAL_CERTIFICATE, late=False)
    assert "SNG-9" in text
    assert "inventado" not in text
