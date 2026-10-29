"""Testes da verificação de CRM (R06): registro local, CFM e modo indisponível."""

from pathlib import Path

import pytest

from sinergia.agents.processing import crm
from sinergia.agents.processing.crm import (
    CfmWebserviceVerifier,
    LocalCrmRegistry,
    UnavailableCrmVerifier,
    build_crm_verifier,
    situation_check,
)
from sinergia.agents.processing.models import CrmStatus
from sinergia.core.errors import ConfigurationError
from sinergia.core.settings import Settings
from tests.conftest import ROOT

REGISTRY = ROOT / "config" / "crm_registry.yaml"


@pytest.mark.parametrize(
    ("number", "status"),
    [
        ("900123", CrmStatus.REGULAR),
        ("900321", CrmStatus.IRREGULAR),
        ("123456", CrmStatus.NOT_FOUND),
    ],
)
def test_local_registry(number: str, status: CrmStatus) -> None:
    assert LocalCrmRegistry(REGISTRY).verify(number, "sp").status is status


def test_retired_doctor_is_explained() -> None:
    check = LocalCrmRegistry(REGISTRY).verify("900321", "SP")
    assert check.situation == "Aposentado"


def test_missing_registry_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        LocalCrmRegistry(tmp_path / "nao_existe.yaml")


def test_unavailable_verifier_sends_to_human() -> None:
    assert UnavailableCrmVerifier().verify("900123", "SP").status is CrmStatus.NOT_VERIFIED


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ("A", CrmStatus.REGULAR),
        ("Regular", CrmStatus.REGULAR),
        ("C", CrmStatus.IRREGULAR),
        ("Irregular", CrmStatus.IRREGULAR),
    ],
)
def test_situation_codes_and_texts(raw: str, status: CrmStatus) -> None:
    assert situation_check(raw, "teste").status is status


def test_cfm_failure_never_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_: object) -> None:
        raise ConnectionError("sem rede")

    monkeypatch.setattr(crm, "soap_client", broken)
    check = CfmWebserviceVerifier("https://exemplo/wsdl", "CHAVE123", 1).verify("900123", "SP")
    assert check.status is CrmStatus.NOT_VERIFIED
    assert "ConnectionError" in check.detail


def test_cfm_response_is_read_without_exact_element_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Service:
        def Consultar(self, crm_number: str, uf: str, key: str) -> dict:  # noqa: N802
            assert (crm_number, uf, key) == ("900123", "SP", "CHAVE123")
            return {"item": [{"nome": "Fulano", "situacao": "A"}]}

    class Client:
        service = Service()

    monkeypatch.setattr(crm, "soap_client", lambda *_: Client())
    check = CfmWebserviceVerifier("https://exemplo/wsdl", "CHAVE123", 1).verify("900123", "sp")
    assert check.status is CrmStatus.REGULAR
    assert check.source == "cfm_webservice"


def test_cfm_without_key_is_a_configuration_error() -> None:
    settings = Settings(_env_file=None, crm_verifier="cfm")
    with pytest.raises(ConfigurationError, match="CFM_ACCESS_KEY"):
        build_crm_verifier(settings)


def test_default_is_no_automatic_verification() -> None:
    assert isinstance(build_crm_verifier(Settings(_env_file=None)), UnavailableCrmVerifier)
