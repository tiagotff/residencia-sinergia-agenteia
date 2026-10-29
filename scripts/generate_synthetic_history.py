"""Carrega um histórico sintético (fictício) com padrões plantados para validar o Agente 3.

Uso:
    python scripts/generate_synthetic_history.py [--date AAAA-MM-DD] [--avaliar]

Grava 100 colaboradores e ~60 afastamentos no banco configurado no .env, salva
samples/colaboradores.csv e samples/alertas_esperados.json. Com --avaliar, roda o
monitoramento na data e mostra precisão e cobertura frente ao esperado.
"""

import argparse
import json
from datetime import date
from pathlib import Path

from sinergia.bootstrap import build_container
from sinergia.core.settings import Settings
from sinergia.synthetic.history import build_history, evaluate, load_history, write_employees_csv


def main() -> None:
    """Gera, grava e (opcionalmente) avalia."""
    args = _args()
    settings = Settings()
    container = build_container(settings)
    reference = args.date or container.clock().date()
    history = build_history(reference)
    repos = (container.intakes, container.absences, container.employees)
    added = load_history(repos, history, container.clock(), container.rules.version)
    print(f"{len(history.employees)} colaboradores e {added} afastamento(s) novo(s) gravados.")
    print(write_employees_csv(history, Path("samples/colaboradores.csv")))
    print(_write_expected(history, reference))
    if args.avaliar:
        summary = container.monitoring.run(reference)
        alerts = container.alerts.list()
        salt = settings.pseudonym_salt.get_secret_value()
        report = evaluate(alerts, summary["suppressed"], history, salt)
        print(json.dumps(report, ensure_ascii=False, indent=2))


def _args() -> argparse.Namespace:
    """Opções da linha de comando."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=date.fromisoformat, help="data de referência")
    parser.add_argument("--avaliar", action="store_true", help="roda e mede o monitoramento")
    return parser.parse_args()


def _write_expected(history, reference: date) -> Path:  # noqa: ANN001
    """Salva o gabarito dos alertas para conferência manual."""
    path = Path("samples/alertas_esperados.json")
    data = {
        "data_referencia": reference.isoformat(),
        "alertas": history.expected,
        "suprimidos": history.expected_suppressed,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
