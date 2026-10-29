"""Comandos do colaborador (Agente 1) e consulta de protocolo."""

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from sinergia.agents.reception.models import MissingItem
from sinergia.agents.reception.service import ReceptionInput, ReceptionResult
from sinergia.bootstrap import Container, build_container
from sinergia.core.domain import CaseStatus, DocumentType
from sinergia.core.errors import NotFoundError
from sinergia.core.settings import Settings

_FILE_ITEMS = {
    MissingItem.FILE,
    MissingItem.FILE_FORMAT,
    MissingItem.FILE_UNREADABLE,
    MissingItem.DOCUMENT_TYPE_NOT_ACCEPTED,
}


def register(sub: Any) -> None:
    """Registra ``submit`` e ``status``."""
    submit = sub.add_parser("submit", help="envia um documento ao Agente 1")
    submit.add_argument("--file", type=Path)
    submit.add_argument("--employee-id")
    submit.add_argument("--type", choices=[t.value for t in DocumentType], dest="declared_type")
    submit.add_argument("--start", type=date.fromisoformat, dest="absence_start")
    submit.add_argument("--channel", default="portal")
    submit.add_argument("--no-interactive", action="store_true")
    submit.set_defaults(handler=submit_document)
    status = sub.add_parser("status", help="mostra entrada, afastamento, pendências e auditoria")
    status.add_argument("protocol")
    status.set_defaults(handler=show_status)


def submit_document(args: argparse.Namespace) -> int:
    """Envia o documento e, no modo interativo, responde ao que o agente pedir."""
    container = build_container(Settings())
    data = _input_from(args.file, args.employee_id, args.declared_type, args.absence_start)
    result = container.reception.start(data.model_copy(update={"channel": args.channel}))
    _print_result(result)
    while result.status is CaseStatus.AWAITING_EMPLOYEE and not args.no_interactive:
        result = container.reception.reply(result.session_id, _ask(result.missing))
        _print_result(result)
    if result.protocol:
        _print_processing(container, result.protocol)
    return 0


def show_status(args: argparse.Namespace) -> int:
    """Mostra o que foi registrado para um protocolo (sem o código CID)."""
    container: Container = build_container(Settings())
    intake = container.intakes.get(args.protocol)
    print(intake.model_dump_json(indent=2, exclude={"file_path"}))
    _print_processing(container, args.protocol)
    for pendency in container.intakes.pendencies_for(args.protocol):
        rule = f" [{pendency.rule_id}]" if pendency.rule_id else ""
        print(f"Pendência{rule}: {pendency.kind} → {pendency.target_area} ({pendency.status})")
    entries = container.audit.list_for(intake.session_id) + container.audit.list_for(args.protocol)
    for entry in entries:
        print(f"Auditoria: {entry.occurred_at} {entry.actor} {entry.action} {entry.rule_ids}")
    return 0


def _print_processing(container: Container, protocol: str) -> None:
    """Resumo do registro criado pelo Agente 2."""
    try:
        absence = container.absences.get(protocol)
    except NotFoundError:
        return
    rules = f" — regras: {', '.join(absence.violated_rules)}" if absence.violated_rules else ""
    period = f"{absence.start_date} a {absence.last_day}" if absence.start_date else "sem período"
    print(f"Processamento: [{absence.status.value}]{rules}")
    print(
        f"  {absence.employee_name} | {period} | {absence.days} dia(s) | "
        f"CRM {absence.crm_number}/{absence.crm_uf} ({absence.crm_status}) | "
        f"CID presente: {'sim' if absence.cid else 'não'} | extração: {absence.extraction_method}"
    )
    _print_tasks(container, absence.session_id)


def _print_tasks(container: Container, session_id: str) -> None:
    """Encaminhamentos do Agente 4 para o caso."""
    tasks = container.tasks.for_session(session_id)
    for task in tasks:
        due = f", prazo {task.due_date:%d/%m/%Y}" if task.due_date else ""
        print(
            f"Encaminhamento #{task.id} [{task.rule_id}] → {task.destination} "
            f"({task.urgency}{due}) [{task.status.value}]"
        )
    if any(task.status.value == "proposto" for task in tasks):
        print(f"  Aguardando confirmação: sinergia escalation show {session_id}")


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
