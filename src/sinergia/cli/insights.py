"""Comandos da crew de insights e do painel."""

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from sinergia.bootstrap import build_container
from sinergia.core.settings import Settings
from sinergia.data.reports import StoredReport

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"


def register(sub: Any) -> None:
    """Registra ``insights run|list|show|approve|return`` e ``dashboard``."""
    insights = sub.add_parser("insights", help="crew de insights (relatório para o SESMT)")
    actions = insights.add_subparsers(required=True)
    run = actions.add_parser("run", help="gera o rascunho do período")
    run.add_argument("--date", type=date.fromisoformat, help="fim do período (padrão: hoje)")
    run.set_defaults(handler=run_report)
    actions.add_parser("list", help="relatórios recentes").set_defaults(handler=list_reports)
    show = actions.add_parser("show", help="mostra um relatório")
    show.add_argument("report_id", type=int)
    show.set_defaults(handler=show_report)
    for name, approve in (("approve", True), ("return", False)):
        decide = actions.add_parser(name, help="aprova" if approve else "devolve")
        decide.add_argument("report_id", type=int)
        decide.add_argument("--by", required=True, help="médico do trabalho (nome)")
        decide.add_argument("--note")
        decide.set_defaults(handler=decide_report, approve=approve)
    dashboard = sub.add_parser("dashboard", help="abre o painel por perfil (Streamlit)")
    dashboard.set_defaults(handler=open_dashboard)


def run_report(args: argparse.Namespace) -> int:
    """Gera o rascunho e mostra como foi feito."""
    report = build_container(Settings()).insights.run(args.date)
    print(_line(report))
    for issue in report.issues:
        print(f"  {issue}")
    print(f"  Para ler: sinergia insights show {report.id}")
    return 0


def list_reports(_: argparse.Namespace) -> int:
    """Relatórios recentes."""
    reports = build_container(Settings()).reports.recent()
    if not reports:
        print("Nenhum relatório.")
    for report in reports:
        print(_line(report))
    return 0


def show_report(args: argparse.Namespace) -> int:
    """Texto do relatório."""
    report = build_container(Settings()).reports.get(args.report_id)
    print(_line(report))
    print()
    print(report.content)
    return 0


def decide_report(args: argparse.Namespace) -> int:
    """Aprovação ou devolução pelo médico do trabalho."""
    container = build_container(Settings())
    report = container.insights.decide(args.report_id, args.approve, args.by, args.note)
    print(_line(report))
    return 0


def open_dashboard(_: argparse.Namespace) -> int:
    """Abre o painel no navegador (Ctrl+C encerra)."""
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print("Erro: instale o extra 'insights' (pip install -e \".[insights]\").", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(DASHBOARD)])


def _line(report: StoredReport) -> str:
    """Uma linha por relatório."""
    return (
        f"#{report.id} {report.period_start:%d/%m/%Y} a {report.period_end:%d/%m/%Y} "
        f"[{report.status.value}] (feito por: {report.method})"
    )
