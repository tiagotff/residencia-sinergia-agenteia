"""Comandos do Agente 4: confirmação dos encaminhamentos, tarefas das áreas e prazos."""

import argparse
import json
from typing import Any

from sinergia.agents.escalation.models import EscalationDecision
from sinergia.bootstrap import build_container
from sinergia.core.settings import Settings
from sinergia.data.tasks import StoredTask, TaskStatus


def register(sub: Any) -> None:
    """Registra ``escalation list|show|decide|sweep`` e ``tasks list|done``."""
    escalation = sub.add_parser("escalation", help="Agente 4 — confirmação e prazos")
    actions = escalation.add_subparsers(required=True)
    actions.add_parser("list", help="sessões aguardando confirmação").set_defaults(
        handler=list_pending
    )
    show = actions.add_parser("show", help="propostas de uma sessão, com a pontuação")
    show.add_argument("session_id")
    show.set_defaults(handler=show_pending)
    _decide_parser(actions)
    actions.add_parser("sweep", help="reescala as tarefas vencidas").set_defaults(handler=sweep)
    _tasks_parser(sub)


def _decide_parser(actions: Any) -> None:
    """``escalation decide``: confirma tudo, exceto o cancelado ou redirecionado."""
    decide = actions.add_parser("decide", help="confirma, cancela ou redireciona")
    decide.add_argument("session_id")
    decide.add_argument("--reviewer", required=True, help="quem confirma (nome e área)")
    decide.add_argument("--cancel", type=int, action="append", default=[], metavar="ID")
    decide.add_argument("--redirect", action="append", default=[], metavar="ID=DESTINO")
    decide.add_argument("--note")
    decide.set_defaults(handler=decide_pending)


def _tasks_parser(sub: Any) -> None:
    """``tasks list`` e ``tasks done``: a visão das áreas."""
    tasks = sub.add_parser("tasks", help="encaminhamentos das áreas")
    actions = tasks.add_subparsers(required=True)
    listed = actions.add_parser("list", help="tarefas por destino e situação")
    listed.add_argument("--destination", help="rh_dp, sesmt, medico_trabalho, gestor...")
    listed.add_argument("--status", choices=[status.value for status in TaskStatus])
    listed.set_defaults(handler=list_tasks)
    done = actions.add_parser("done", help="marca a tarefa como resolvida")
    done.add_argument("task_id", type=int)
    done.add_argument("--by", required=True, help="quem resolveu (nome e área)")
    done.add_argument("--note")
    done.set_defaults(handler=complete_task)


def list_pending(_: argparse.Namespace) -> int:
    """Sessões com encaminhamentos aguardando confirmação."""
    pending = build_container(Settings()).escalation.pending()
    if not pending:
        print("Nenhum encaminhamento aguardando confirmação.")
    for item in pending:
        rules = sorted({task["rule_id"] for task in item.payload["tasks"]})
        print(
            f"{item.session_id}  [{item.origin}]  {len(item.payload['tasks'])} proposta(s): "
            f"{', '.join(rules)}"
        )
    return 0


def show_pending(args: argparse.Namespace) -> int:
    """Propostas de uma sessão: destino, urgência, detalhe, utilidade e texto."""
    item = build_container(Settings()).escalation.get(args.session_id)
    for task in item.payload["tasks"]:
        mark = " (principal)" if task["primary_choice"] else ""
        print(f"#{task['id']} [{task['rule_id']}] {task['title']} → {task['destination']}{mark}")
        print(
            f"   urgência {task['urgency']} | detalhe {task['detail']} | "
            f"utilidade {task['utility']} | prazo {task['deadline'] or '—'}"
        )
        print(f"   conta: {json.dumps(task['breakdown'], ensure_ascii=False)}")
        print(f"   {task['summary']}")
    return 0


def decide_pending(args: argparse.Namespace) -> int:
    """Confirma a sessão e mostra como ficou cada tarefa."""
    decision = EscalationDecision(
        reviewer=args.reviewer,
        cancel=args.cancel,
        redirect=dict(_split(item) for item in args.redirect),
        note=args.note,
    )
    for task in build_container(Settings()).escalation.decide(args.session_id, decision):
        print(_line(task))
    return 0


def sweep(_: argparse.Namespace) -> int:
    """Acompanhamento de prazos (rodar diariamente)."""
    result = build_container(Settings()).escalation.sweep()
    print(
        f"Reescalonadas: {len(result.reescalated)} | vencidas sem novo destino: "
        f"{len(result.expired)}"
    )
    return 0


def list_tasks(args: argparse.Namespace) -> int:
    """Tarefas filtradas, com o texto escrito para o destino."""
    status = TaskStatus(args.status) if args.status else None
    tasks = build_container(Settings()).tasks.find(status, args.destination)
    if not tasks:
        print("Nenhum encaminhamento.")
    for task in tasks:
        print(_line(task))
        print(f"   {task.summary}")
    return 0


def complete_task(args: argparse.Namespace) -> int:
    """A área informa que resolveu."""
    task = build_container(Settings()).escalation.complete(args.task_id, args.by, args.note)
    print(_line(task))
    return 0


def _line(task: StoredTask) -> str:
    """Uma linha por tarefa."""
    due = f", prazo {task.due_date:%d/%m/%Y}" if task.due_date else ""
    return (
        f"#{task.id} [{task.rule_id}] → {task.destination} ({task.urgency}{due}) "
        f"[{task.status.value}]"
    )


def _split(item: str) -> tuple[int, str]:
    """Converte 'id=destino' em par."""
    if "=" not in item:
        raise ValueError(f"Use ID=DESTINO em --redirect (recebido: {item}).")
    task_id, destination = item.split("=", 1)
    return int(task_id), destination.strip()
