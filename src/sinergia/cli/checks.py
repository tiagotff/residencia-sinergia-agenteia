"""Checagens de integração: LLM (Groq) e webservice do CFM."""

import argparse
from typing import Any

from sinergia.agents.processing.crm import build_crm_verifier, describe_cfm_service
from sinergia.core.llm import build_chat_model
from sinergia.core.settings import Settings


def register(sub: Any) -> None:
    """Registra ``check-llm`` e ``check-cfm``."""
    llm = sub.add_parser("check-llm", help="testa a conexão com o provedor de LLM")
    llm.set_defaults(handler=check_llm)
    cfm = sub.add_parser("check-cfm", help="mostra o WSDL do CFM ou consulta um CRM")
    cfm.add_argument("--crm", help="número do CRM para consultar (exige CRM_VERIFIER=cfm)")
    cfm.add_argument("--uf", default="SP")
    cfm.set_defaults(handler=check_cfm)


def check_llm(_: argparse.Namespace) -> int:
    """Faz uma chamada mínima, sem dados pessoais, ao provedor configurado."""
    settings = Settings()
    model = build_chat_model(settings)
    if model is None:
        print("LLM_PROVIDER=none: nenhum LLM configurado.")
        return 0
    try:
        reply = model.invoke("Responda apenas com a palavra: ok")
    except Exception as exc:  # noqa: BLE001 — a checagem traduz qualquer falha do provedor
        print(f"Falha ao chamar {settings.llm_provider} / {settings.llm_model}: {_short(exc)}")
        print("Confira GROQ_API_KEY e LLM_MODEL no .env (o modelo precisa estar liberado).")
        return 1
    print(f"{settings.llm_provider} / {settings.llm_model} respondeu: {reply.content}")
    return 0


def check_cfm(args: argparse.Namespace) -> int:
    """Sem --crm, lista as operações do WSDL; com --crm, consulta a situação."""
    settings = Settings()
    try:
        if args.crm:
            check = build_crm_verifier(settings).verify(args.crm, args.uf)
            print(f"[{check.status.value}] {check.detail} (fonte: {check.source})")
        else:
            print(describe_cfm_service(settings.cfm_wsdl_url, settings.cfm_timeout_seconds))
    except Exception as exc:  # noqa: BLE001 — a checagem traduz qualquer falha de rede
        print(f"Não foi possível acessar o webservice do CFM: {_short(exc)}")
        return 1
    return 0


def _short(exc: Exception) -> str:
    """Primeira linha da mensagem de erro, com o tipo."""
    first_line = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {first_line[:200]}"
