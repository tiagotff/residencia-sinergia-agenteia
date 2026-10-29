"""Redação dos alertas: texto-base, marcadores e reescrita pelo LLM com verificação."""

from datetime import date

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from sinergia.agents.monitoring.writer import LlmWriter, TemplateWriter, base_text, preserves
from sinergia.data.alerts import Alert

ALERT = Alert(
    rule_id="A02",
    scope_type="setor",
    scope="Câmara Fria",
    period_start=date(2026, 9, 29),
    period_end=date(2026, 10, 28),
    metric="pessoas_mesmo_grupo_cid",
    value=3,
    threshold=3,
    group_size=12,
    sensitive=True,
    details={"grupo_cid": "M54"},
)


def test_base_text_uses_placeholder_instead_of_cid() -> None:
    text = base_text(ALERT)
    assert "{GRUPO_CID}" in text and "M54" not in text


def test_template_fills_cid_and_uses_decimal_comma() -> None:
    assert "M54" in TemplateWriter().explain(ALERT)
    spike = ALERT.model_copy(
        update={
            "rule_id": "A01",
            "value": 0.0964,
            "threshold": 0.0289,
            "reference": 0.009,
            "sensitive": False,
        }
    )
    assert "9,6%" in TemplateWriter().explain(spike)


def test_llm_rewrite_is_kept_when_numbers_and_markers_survive() -> None:
    base = base_text(ALERT)
    rewrite = "Atenção: " + base
    writer = LlmWriter(FakeListChatModel(responses=[rewrite]), TemplateWriter())
    assert writer.explain(ALERT).startswith("Atenção:")
    assert "M54" in writer.explain(ALERT)


def test_llm_rewrite_that_drops_a_number_falls_back_to_template() -> None:
    writer = LlmWriter(
        FakeListChatModel(responses=["Há um grupo com afastamentos."]), TemplateWriter()
    )
    assert writer.explain(ALERT) == TemplateWriter().explain(ALERT)


def test_preserves_requires_every_number_and_marker() -> None:
    base = base_text(ALERT)
    assert preserves(base, base)
    assert not preserves(base, base.replace("{GRUPO_CID}", "M54"))
    assert not preserves(base, "")
