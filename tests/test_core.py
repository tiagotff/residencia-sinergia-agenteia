"""Testes da fundação: regras, LLM configurável e auditoria."""

from pathlib import Path

import pytest

from sinergia.core.domain import DocumentType
from sinergia.core.errors import ConfigurationError
from sinergia.core.llm import build_chat_model
from sinergia.core.rules import RuleCatalog, load_rules
from sinergia.core.settings import Settings
from sinergia.data.audit import AuditLog


def test_rules_load_reception_parameters(rules: RuleCatalog) -> None:
    assert rules.version
    assert {"R01", "R02", "R03"} <= set(rules.catalog)
    assert DocumentType.MEDICAL_CERTIFICATE in rules.reception.accepted_document_types
    assert rules.reception.max_file_size_bytes == 10 * 1024 * 1024


def test_missing_rules_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="não encontrado"):
        load_rules(tmp_path / "nao_existe.yaml")


def test_invalid_rules_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text("version: '1'\ncatalog: {}\nreception: {}\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="inválido"):
        load_rules(path)


def test_no_llm_when_provider_is_none(settings: Settings) -> None:
    assert build_chat_model(settings) is None


def test_groq_without_key_raises(settings: Settings) -> None:
    groq = settings.model_copy(update={"llm_provider": "groq", "groq_api_key": None})
    with pytest.raises(ConfigurationError, match="GROQ_API_KEY"):
        build_chat_model(groq)


def test_groq_model_is_built_with_key(settings: Settings) -> None:
    groq = Settings(_env_file=None, llm_provider="groq", groq_api_key="chave-de-teste")
    model = build_chat_model(groq)
    assert model is not None
    assert type(model).__name__ == "ChatGroq"
    assert "chave-de-teste" not in repr(model)


def test_audit_records_rules_version(container) -> None:
    audit: AuditLog = container.audit
    audit.record("teste", "acao", "ref-1", ["R01"], {"chave": "valor"})
    [entry] = audit.list_for("ref-1")
    assert entry.rule_ids == ["R01"]
    assert entry.rules_version == container.rules.version
    assert entry.details == {"chave": "valor"}
