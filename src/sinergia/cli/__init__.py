"""Linha de comando ``sinergia`` para validar os agentes localmente.

Exemplos:
    sinergia check-llm
    sinergia check-cfm
    sinergia submit --file samples/atestado_medico.pdf --employee-id 1001 --start 2026-10-27
    sinergia status SNG-20261028-ABC123
    sinergia review list
    sinergia review decide SNG-20261028-ABC123 --approve --reviewer "Ana (RH)" --set signed=sim
    sinergia vacation import samples/ferias.csv
"""

import argparse
import sys

from pydantic import ValidationError

from sinergia.cli import checks, reception, review, vacations
from sinergia.core.errors import SinergiaError


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do comando ``sinergia``."""
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except ValidationError as exc:
        print(f"Erro: {exc.errors()[0]['msg'].removeprefix('Value error, ')}", file=sys.stderr)
        return 1
    except (SinergiaError, ValueError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    """Reúne os subcomandos de cada módulo."""
    parser = argparse.ArgumentParser(prog="sinergia", description="Sinergia — agentes")
    sub = parser.add_subparsers(required=True)
    for module in (checks, reception, review, vacations):
        module.register(sub)
    return parser
