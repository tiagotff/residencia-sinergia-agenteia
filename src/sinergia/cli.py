"""Linha de comando para validar o Agente 1 localmente.

Exemplos:
    sinergia check-llm
    sinergia submit --file samples/atestado_medico.pdf --employee-id 1001 --start 2026-10-27
    sinergia status SNG-20261028-ABC123
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from sinergia.agents.reception.models import MissingItem
from sinergia.agents.reception.service import ReceptionInput, ReceptionResult
from sinergia.bootstrap import Container, build_container
from sinergia.core.domain import CaseStatus, DocumentType
from sinergia.core.errors import SinergiaError
from sinergia.core.llm import build_chat_model
from sinergia.core.settings import Settings

_FILE_ITEMS = {
    MissingItem.FILE,
    MissingItem.FILE_FORMAT,
    MissingItem.FILE_UNREADABLE,
    MissingItem.DOCUMENT_TYPE_NOT_ACCEPTED,
}


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do comando ``sinergia``."""
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except SinergiaError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    """Define os subcomandos."""
    parser = argparse.ArgumentParser(prog="sinergia", description="Sinergia — Agente 1")
    sub = parser.add_subparsers(required=True)
    check = sub.add_parser("check-llm", help="testa a conexão com o provedor de LLM")
    check.set_defaults(handler=_check_llm)
    submit = sub.add_parser("submit", help="envia um documento ao Agente 1")
    submit.add_argument("--file", type=Path)
    submit.add_argument("--employee-id")
    submit.add_argument("--type", choices=[t.value for t in DocumentType], dest="declared_type")
    submit.add_argument("--start", type=date.fromisoformat, dest="absence_start")
    submit.add_argument("--channel", default="portal")
    submit.add_argument("--no-interactive", action="store_true")
    submit.set_defaults(handler=_submit)
    status = sub.add_parser("status", help="mostra a linha de entrada, pendências e auditoria")
    status.add_argument("protocol")
    status.set_defaults(handler=_status)
    return parser


def _check_llm(_: argparse.Namespace) -> int:
    """Faz uma chamada mínima, sem dados pessoais, ao provedor configurado."""
    settings = Settings()
    model = build_chat_model(settings)
    if model is None:
        print("LLM_PROVIDER=none: nenhum LLM configurado.")
        return 0
    reply = model.invoke("Responda apenas com a palavra: ok")
    print(f"{settings.llm_provider} / {settings.llm_model} respondeu: {reply.content}")
    return 0


def _submit(args: argparse.Namespace) -> int:
    """Envia o documento e, no modo interativo, responde ao que o agente pedir."""
    container = build_container(Settings())
    data = _input_from(args.file, args.employee_id, args.declared_type, args.absence_start)
    result = container.reception.start(data.model_copy(update={"channel": args.channel}))
    _print_result(result)
    while result.status is CaseStatus.AWAITING_EMPLOYEE and not args.no_interactive:
        result = container.reception.reply(result.session_id, _ask(result.missing))
        _print_result(result)
    return 0


def _status(args: argparse.Namespace) -> int:
    """Mostra o que foi registrado para um protocolo."""
    container: Container = build_container(Settings())
    intake = container.intakes.get(args.protocol)
    print(intake.model_dump_json(indent=2, exclude={"file_path"}))
    for pendency in container.intakes.pendencies_for(args.protocol):
        print(f"Pendência: {pendency.kind} → {pendency.target_area} ({pendency.status})")
    for entry in container.audit.list_for(intake.session_id) + container.audit.list_for(
        args.protocol
    ):
        print(f"Auditoria: {entry.occurred_at} {entry.action} regras={entry.rule_ids}")
    return 0


def _input_from(
    file: Path | None, employee_id: str | None, declared: str | None, start: date | None
) -> ReceptionInput:
    """Monta a entrada a partir de argumentos ou respostas digitadas."""
    return ReceptionInput(
        employee_id=employee_id or None,
        declared_type=DocumentType(declared) if declared else None,
        absence_start=start,
        file_name=file.name if file else None,
        content=file.read_bytes() if file else None,
    )


def _ask(missing: list[str]) -> ReceptionInput:
    """Pergunta no terminal só o que o agente pediu."""
    items = {MissingItem(value) for value in missing}
    file = _prompt_path() if items & _FILE_ITEMS else None
    declared = _prompt_type() if MissingItem.DOCUMENT_TYPE in items else None
    employee = input("Matrícula: ").strip() if MissingItem.EMPLOYEE_ID in items else None
    start = _prompt_date() if MissingItem.ABSENCE_START in items else None
    return _input_from(file, employee, declared, start)


def _prompt_path() -> Path | None:
    """Pede o caminho de um novo arquivo."""
    raw = input("Caminho do novo arquivo (vazio para pular): ").strip().strip('"')
    return Path(raw) if raw else None


def _prompt_type() -> str | None:
    """Pede o tipo do documento."""
    accepted = [
        t.value for t in DocumentType if t not in (DocumentType.OTHER, DocumentType.UNKNOWN)
    ]
    raw = input(f"Tipo do documento ({', '.join(accepted)}): ").strip()
    return raw if raw in accepted else None


def _prompt_date() -> date | None:
    """Pede a data de início do afastamento."""
    raw = input("Data de início (AAAA-MM-DD): ").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _print_result(result: ReceptionResult) -> None:
    """Mostra a resposta do agente."""
    print(f"\n[{result.status.value}] {result.message}")
    if result.protocol:
        print(f"Protocolo: {result.protocol}")


if __name__ == "__main__":
    raise SystemExit(main())
