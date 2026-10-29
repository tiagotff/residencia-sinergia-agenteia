"""Gera documentos sintéticos (fictícios) para validar o Agente 1.

Uso:
    python scripts/generate_synthetic_documents.py [pasta_de_saida]
"""

import sys
from pathlib import Path

from sinergia.synthetic.documents import generate_samples


def main() -> None:
    """Grava as amostras na pasta informada (padrão: samples/)."""
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("samples")
    for path in generate_samples(folder):
        print(path)


if __name__ == "__main__":
    main()
