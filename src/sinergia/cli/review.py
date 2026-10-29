"""Comandos do revisor humano (fila do Agente 2)."""

import argparse
import json
from typing import Any

from sinergia.agents.processing.models import ReviewDecision
from sinergia.bootstrap import build_container
from sinergia.core.settings import Settings


def register(sub: Any) -> None:
    """Registra ``review list``, ``review show`` e ``review decide``."""
    review = sub.add_parser("review", help="fila de revisão humana do Agente 2")
    actions = review.add_subparsers(required=True)
    actions.add_parser("list", help="casos aguardando decisão").set_defaults(handler=list_cases)
    show = actions.add_parser("show", help="detalhes de um caso")
    show.add_argument("protocol")
    show.set_defaults(handler=show_case)
    decide = actions.add_parser("decide", help="aprovar (com correções) ou invalidar")
    decide.add_argument("protocol")
    choice = decide.add_mutually_exclusive_group(required=True)
    choice.add_argument("--approve", action="store_const", const="aprovar", dest="decision")
    choice.add_argument("--invalidate", action="store_const", const="invalidar", dest="decision")
    decide.add_argument("--reviewer", required=True, help="quem decide (nome e área)")
    decide.add_argument("--set", action="append", default=[], metavar="CAMPO=VALOR")
    decide.add_argument("--note")
    decide.set_defaults(handler=decide_case)


def list_cases(_: argparse.Namespace) -> int:
    """Lista a fila de revisão."""
    cases = build_container(Settings()).review.pending()
    if not cases:
        print("Nenhum caso aguardando revisão.")
    for case in cases:
        rules = sorted({item["rule_id"] for item in case.payload["violations"]})
        print(f"{case.protocol}  [{case.status}]  regras: {', '.join(rules)}")
    return 0


def show_case(args: argparse.Namespace) -> int:
    """Mostra o que o revisor precisa conferir."""
    case = build_container(Settings()).review.get(args.protocol)
    print(json.dumps(case.payload, indent=2, ensure_ascii=False))
    return 0


def decide_case(args: argparse.Namespace) -> int:
    """Registra a decisão e mostra a nova situação do afastamento."""
    decision = ReviewDecision(
        decision=args.decision,
        reviewer=args.reviewer,
        corrections=dict(_split(item) for item in args.set),
        note=args.note,
    )
    absence = build_container(Settings()).review.decide(args.protocol, decision)
    rules = f" — regras: {', '.join(absence.violated_rules)}" if absence.violated_rules else ""
    print(f"{absence.protocol}: [{absence.status.value}]{rules}")
    return 0


def _split(item: str) -> tuple[str, str]:
    """Converte 'campo=valor' em par."""
    if "=" not in item:
        raise ValueError(f"Use CAMPO=VALOR em --set (recebido: {item}).")
    name, value = item.split("=", 1)
    return name.strip(), value.strip()
