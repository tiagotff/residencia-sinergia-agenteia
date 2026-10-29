"""Comandos do Agente 3: cadastro de colaboradores, execução do monitoramento e alertas."""

import argparse
from datetime import date
from pathlib import Path
from typing import Any

from sinergia.bootstrap import build_container
from sinergia.core.settings import Settings
from sinergia.data.alerts import StoredAlert


def register(sub: Any) -> None:
    """Registra ``employees import``, ``monitor run`` e ``alerts list``."""
    employees = sub.add_parser("employees", help="cadastro usado pelo monitoramento")
    imported = employees.add_subparsers(required=True).add_parser(
        "import", help="CSV: employee_id,sector,role,shift,critical_role"
    )
    imported.add_argument("csv", type=Path)
    imported.set_defaults(handler=import_employees)
    monitor = sub.add_parser("monitor", help="Agente 3 — monitoramento")
    run = monitor.add_subparsers(required=True).add_parser("run", help="aplica A01–A05")
    run.add_argument("--date", type=date.fromisoformat, help="AAAA-MM-DD (padrão: hoje)")
    run.set_defaults(handler=run_monitoring)
    alerts = sub.add_parser("alerts", help="alertas gerados pelo Agente 3")
    listed = alerts.add_subparsers(required=True).add_parser("list", help="lista os alertas")
    listed.add_argument("--status", help="ex.: aberto")
    listed.set_defaults(handler=list_alerts)


def import_employees(args: argparse.Namespace) -> int:
    """Importa o cadastro exportado da folha."""
    container = build_container(Settings())
    count = container.employees.import_csv(args.csv, container.clock())
    print(f"{count} colaborador(es) importado(s).")
    return 0


def run_monitoring(args: argparse.Namespace) -> int:
    """Roda o ciclo e mostra o resumo."""
    summary = build_container(Settings()).monitoring.run(args.date)
    print(f"Data de referência: {summary['reference_date']}")
    print(f"Colaboradores ativos: {summary['employees']}")
    print(f"Alertas novos: {len(summary['created'])}; já conhecidos: {summary['already_known']}")
    for group in summary["suppressed"]:
        print(f"  A05: grupo {group} pequeno demais — dados não exibidos.")
    return 0


def list_alerts(args: argparse.Namespace) -> int:
    """Lista os alertas com a explicação."""
    alerts = build_container(Settings()).alerts.list(args.status)
    if not alerts:
        print("Nenhum alerta.")
    for alert in alerts:
        print(_line(alert))
    return 0


def _line(alert: StoredAlert) -> str:
    """Uma linha por alerta, marcando os que têm dado de saúde."""
    mark = " [sensível]" if alert.sensitive else ""
    return f"#{alert.id} {alert.rule_id} {alert.status}{mark}: {alert.explanation}"
