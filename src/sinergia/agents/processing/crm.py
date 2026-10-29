"""Verificação do CRM (R06), com três estratégias intercambiáveis.

- ``CfmWebserviceVerifier``: webservice SOAP oficial do CFM. Exige a chave de acesso que o
  CFM emite para a instituição (Res. CFM 2.129/2015). O cliente lê o WSDL do próprio CFM.
- ``LocalCrmRegistry``: registro fictício em YAML, para validação local e testes.
- ``UnavailableCrmVerifier``: sem verificação automática; o caso segue para revisão humana.

Nenhuma falha de consulta rejeita um atestado: vira "não verificado" e decisão humana.
"""

import contextlib
import io
from pathlib import Path
from typing import Any, Protocol

import yaml

from sinergia.agents.processing.models import CrmCheck, CrmStatus
from sinergia.agents.reception.classifier import normalize
from sinergia.core.errors import ConfigurationError
from sinergia.core.settings import Settings

CFM_SITUATIONS = {
    "A": "Regular",
    "E": "Inoperante",
    "F": "Falecido",
    "L": "Cancelado",
    "P": "Aposentado",
    "C": "Cassado",
    "T": "Transferido",
}


class CrmVerifier(Protocol):
    """Contrato da verificação do CRM."""

    def verify(self, crm_number: str, uf: str) -> CrmCheck:
        """Consulta a situação do CRM na UF."""
        ...


class UnavailableCrmVerifier:
    """Usado quando não há fonte configurada: tudo vai para conferência humana."""

    def verify(self, crm_number: str, uf: str) -> CrmCheck:
        """Sempre devolve 'não verificado', com o motivo."""
        return CrmCheck(
            status=CrmStatus.NOT_VERIFIED,
            detail="Verificação automática do CRM não configurada; conferir manualmente.",
            source="nenhuma",
        )


class LocalCrmRegistry:
    """Registro fictício de CRMs em YAML: {UF: {numero: {nome, situacao}}}."""

    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise ConfigurationError(f"Registro local de CRMs não encontrado: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self._registry = {str(uf).upper(): entries or {} for uf, entries in raw.items()}

    def verify(self, crm_number: str, uf: str) -> CrmCheck:
        """Procura o CRM no registro local."""
        entry = self._registry.get(uf.upper(), {}).get(crm_number)
        if entry is None:
            return CrmCheck(
                status=CrmStatus.NOT_FOUND,
                detail=f"CRM {crm_number}/{uf} não consta no registro.",
                source="registro_local",
            )
        return situation_check(str(entry.get("situacao", "")), "registro_local")


class CfmWebserviceVerifier:
    """Cliente do webservice ``ServicoConsultaMedicos`` do CFM (SOAP 1.2).

    Chama a operação ``Consultar`` com CRM, UF e chave, nessa ordem. Rode
    ``sinergia check-cfm`` para conferir a assinatura da operação no WSDL vigente.
    """

    def __init__(self, wsdl_url: str, access_key: str, timeout: float) -> None:
        self._wsdl_url = wsdl_url
        self._access_key = access_key
        self._timeout = timeout
        self._client: Any = None

    def verify(self, crm_number: str, uf: str) -> CrmCheck:
        """Consulta o CFM; qualquer falha vira 'não verificado'."""
        try:
            result = self._service().Consultar(crm_number, uf.upper(), self._access_key)
        except Exception as exc:  # noqa: BLE001 — indisponibilidade do CFM não bloqueia o fluxo
            return CrmCheck(
                status=CrmStatus.NOT_VERIFIED,
                detail=f"Consulta ao CFM indisponível ({type(exc).__name__}); conferir à mão.",
                source="cfm_webservice",
            )
        return _check_from_response(result)

    def _service(self) -> Any:
        """Cria o cliente SOAP a partir do WSDL, só no primeiro uso."""
        if self._client is None:
            self._client = soap_client(self._wsdl_url, self._timeout)
        return self._client.service


def soap_client(wsdl_url: str, timeout: float) -> Any:
    """Cliente zeep com tempo limite nas chamadas."""
    from zeep import Client
    from zeep.transports import Transport

    return Client(wsdl_url, transport=Transport(timeout=timeout, operation_timeout=timeout))


def describe_cfm_service(wsdl_url: str, timeout: float) -> str:
    """Texto do WSDL do CFM (operações e parâmetros), para conferência manual."""
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        soap_client(wsdl_url, timeout).wsdl.dump()
    return output.getvalue()


def situation_check(situation: str, source: str) -> CrmCheck:
    """Traduz o código ou texto de situação do CFM em ``CrmCheck``."""
    raw = situation.strip()
    code = raw.upper() if len(raw) == 1 else _code_from_text(raw)
    label = CFM_SITUATIONS.get(code, raw or "desconhecida")
    status = CrmStatus.REGULAR if code == "A" else CrmStatus.IRREGULAR
    return CrmCheck(status=status, situation=label, detail=f"Situação: {label}.", source=source)


def _code_from_text(text: str) -> str:
    """'Regular' → 'A'; demais textos ficam como estão."""
    words = normalize(text).split()
    return "A" if "regular" in words else text


def _check_from_response(result: Any) -> CrmCheck:
    """Lê a situação na resposta do CFM, sem depender do nome exato do elemento."""
    from zeep.helpers import serialize_object

    situation = _find_value(serialize_object(result), "situacao")
    if not situation:
        return CrmCheck(
            status=CrmStatus.NOT_FOUND,
            detail="CRM não encontrado na consulta ao CFM.",
            source="cfm_webservice",
        )
    return situation_check(str(situation), "cfm_webservice")


def _find_value(data: Any, key_fragment: str) -> Any:
    """Busca recursiva pela primeira chave que contenha o fragmento (sem acentos)."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key_fragment in normalize(str(key)) and not isinstance(value, dict | list):
                return value
        children = list(data.values())
    elif isinstance(data, list):
        children = data
    else:
        return None
    return next((found for child in children if (found := _find_value(child, key_fragment))), None)


def build_crm_verifier(settings: Settings) -> CrmVerifier:
    """Escolhe a estratégia conforme ``CRM_VERIFIER`` no .env."""
    if settings.crm_verifier == "local":
        return LocalCrmRegistry(settings.crm_registry_path)
    if settings.crm_verifier == "cfm":
        if settings.cfm_access_key is None or not settings.cfm_access_key.get_secret_value():
            raise ConfigurationError("CFM_ACCESS_KEY não definida no .env para CRM_VERIFIER=cfm.")
        return CfmWebserviceVerifier(
            settings.cfm_wsdl_url,
            settings.cfm_access_key.get_secret_value(),
            settings.cfm_timeout_seconds,
        )
    return UnavailableCrmVerifier()
