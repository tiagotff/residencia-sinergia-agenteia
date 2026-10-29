"""Comandos de férias (fonte da R07 até haver integração com a folha)."""

import argparse
from pathlib import Path
from typing import Any

from sinergia.bootstrap import build_container
from sinergia.core.settings import Settings
from sinergia.data.vacations import Vacation


def register(sub: Any) -> None:
    """Registra ``vacation add``, ``vacation import`` e ``vacation list``."""
    vacation = sub.add_parser("vacation", help="férias usadas pela regra R07")
    actions = vacation.add_subparsers(required=True)
    add = actions.add_parser("add", help="cadastra um período de férias")
    add.add_argument("--employee-id", required=True)
    add.add_argument("--start", required=True, help="AAAA-MM-DD ou DD/MM/AAAA")
    add.add_argument("--end", required=True, help="AAAA-MM-DD ou DD/MM/AAAA")
    add.set_defaults(handler=add_vacation)
    imported = actions.add_parser("import", help="importa CSV: employee_id,start_date,end_date")
    imported.add_argument("csv", type=Path)
    imported.set_defaults(handler=import_vacations)
    listed = actions.add_parser("list", help="férias de um colaborador")
    listed.add_argument("--employee-id", required=True)
    listed.set_defaults(handler=list_vacations)


def add_vacation(args: argparse.Namespace) -> int:
    """Cadastra um período."""
    container = build_container(Settings())
    vacation = Vacation(employee_id=args.employee_id, start_date=args.start, end_date=args.end)
    added = container.vacations.add(vacation, container.clock())
    print("Férias cadastradas." if added else "Esse período já estava cadastrado.")
    return 0


def import_vacations(args: argparse.Namespace) -> int:
    """Importa um CSV exportado da folha (vírgula ou ponto e vírgula)."""
    container = build_container(Settings())
    count = container.vacations.import_csv(args.csv, container.clock())
    print(f"{count} período(s) de férias importado(s).")
    return 0


def list_vacations(args: argparse.Namespace) -> int:
    """Lista as férias do colaborador."""
    vacations = build_container(Settings()).vacations.for_employee(args.employee_id)
    if not vacations:
        print("Nenhum período de férias cadastrado.")
    for item in vacations:
        print(f"{item.start_date:%d/%m/%Y} a {item.end_date:%d/%m/%Y} ({item.source})")
    return 0
